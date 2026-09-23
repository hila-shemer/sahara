/* The SDL2 backend of the live session (gui/live.h): sahara-gui's
 * window, input and clock. Moved verbatim out of sdl_main.c when the
 * session was split from its window system; the pointer-grab state
 * (captured, button mask, last position) moved with it, because only
 * a backend that owns a grab has any. This TU is the sanctioned SDL
 * carve-out (allow_banned, out of the source audits). */
#include <SDL2/SDL.h>

#include <stdio.h>
#include <stdlib.h>

#include "gui/live.h"

const char *const se_live_prog = "sahara-gui";

static SDL_Window *win;
static SDL_Renderer *ren;
static SDL_Texture *tex;
static bool captured;    /* pointer grabbed + hidden */
static uint8_t btn_mask; /* current sahara button state (live mode) */
static int32_t ptr_x, ptr_y;

static void die(const char *msg)
{
    fprintf(stderr, "sahara-gui: %s\n", msg);
    exit(1);
}

int SeLiveBe_option(int argc, char **argv, int i)
{
    (void)argc;
    (void)argv;
    (void)i;
    return 0; /* sahara-gui's CLI is live_main's, unchanged */
}

void SeLiveBe_init(SeLive *lv, uint64_t w, uint64_t h, bool scripted)
{
    (void)lv;
    (void)scripted; /* the scripted gate still opens a (dummy) window */
    /* Window at the reset mode, non-resizable: META cannot carry a
     * display mode, so replay depends on the fixed reset default
     * (display.md 1); resize is deferred to v2 (frontend-notes.md). */
    if (SDL_Init(SDL_INIT_VIDEO) != 0)
        die("SDL_Init failed");
    win = SDL_CreateWindow("sahara", SDL_WINDOWPOS_UNDEFINED,
                           SDL_WINDOWPOS_UNDEFINED, (int)w, (int)h, 0);
    if (!win)
        die("SDL_CreateWindow failed");
    ren = SDL_CreateRenderer(win, -1, 0);
    if (!ren)
        die("SDL_CreateRenderer failed");
    tex = SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888,
                            SDL_TEXTUREACCESS_STREAMING, (int)w, (int)h);
    if (!tex)
        die("SDL_CreateTexture failed");
}

void SeLiveBe_fini(void)
{
    SDL_DestroyTexture(tex);
    SDL_DestroyRenderer(ren);
    SDL_DestroyWindow(win);
    SDL_Quit();
}

uint64_t SeLiveBe_now_ms(void)
{
    return SDL_GetTicks64();
}

void SeLiveBe_present(const uint8_t *frame, uint64_t w, uint64_t h)
{
    (void)h;
    (void)SDL_UpdateTexture(tex, NULL, frame, (int)(4u * w));
    (void)SDL_RenderClear(ren);
    (void)SDL_RenderCopy(ren, tex, NULL, NULL);
    SDL_RenderPresent(ren);
}

void SeLiveBe_wait_input(int timeout_ms)
{
    (void)SDL_WaitEventTimeout(NULL, timeout_ms);
}

void SeLiveBe_delay(uint64_t ms)
{
    SDL_Delay((Uint32)ms);
}

void SeLiveBe_release_capture(void)
{
    if (captured) {
        captured = false;
        SDL_SetWindowGrab(win, SDL_FALSE);
        SDL_ShowCursor(SDL_ENABLE);
    }
    btn_mask = 0;
}

static uint8_t sdl_button_bit(uint8_t sdl_button)
{
    /* SDL numbers left/middle/right 1/2/3; the platform packs bit 0
     * left, bit 1 right, bit 2 middle (PLATFORM-SPEC 6). */
    switch (sdl_button) {
    case SDL_BUTTON_LEFT: return 1u;
    case SDL_BUTTON_RIGHT: return 2u;
    case SDL_BUTTON_MIDDLE: return 4u;
    default: return 0u; /* X1/X2: no field, discarded */
    }
}

static void handle_sdl_event(SeLive *lv, const SDL_Event *e)
{
    switch (e->type) {
    case SDL_QUIT:
        SeLive_host_quit(lv);
        return;
    case SDL_KEYDOWN:
    case SDL_KEYUP: {
        /* SDL scancodes are page-7 usages; the subset filter and the
         * alternation guard live in the translator. Keyboard capture
         * follows window focus (Appendix A): SDL only routes key
         * events to the focused window, so no extra gate is needed. */
        uint32_t usage = (uint32_t)e->key.keysym.scancode;
        SeLive_host_key(lv, usage, e->type == SDL_KEYDOWN,
                        e->key.repeat != 0);
        if (captured && SeLive_chord(lv))
            SeLive_host_capture_lost(lv); /* left Ctrl+Alt releases */
        return;
    }
    case SDL_WINDOWEVENT:
        if (e->window.event == SDL_WINDOWEVENT_FOCUS_LOST)
            SeLive_host_capture_lost(lv);
        return;
    case SDL_MOUSEBUTTONDOWN:
        if (!captured) {
            /* Click-to-capture; the capturing click itself is
             * delivered to the guest (Appendix A). */
            captured = true;
            SDL_SetWindowGrab(win, SDL_TRUE);
            SDL_ShowCursor(SDL_DISABLE);
        }
        btn_mask |= sdl_button_bit(e->button.button);
        ptr_x = e->button.x;
        ptr_y = e->button.y;
        SeLive_host_mouse(lv, ptr_x, ptr_y, btn_mask);
        return;
    case SDL_MOUSEBUTTONUP:
        if (!captured)
            return;
        btn_mask &= (uint8_t)~sdl_button_bit(e->button.button);
        ptr_x = e->button.x;
        ptr_y = e->button.y;
        SeLive_host_mouse(lv, ptr_x, ptr_y, btn_mask);
        return;
    case SDL_MOUSEMOTION:
        if (!captured)
            return; /* uncaptured motion is invisible to the guest */
        ptr_x = e->motion.x;
        ptr_y = e->motion.y;
        SeLive_host_mouse(lv, ptr_x, ptr_y, btn_mask);
        return;
    default:
        return;
    }
}

void SeLiveBe_poll(SeLive *lv)
{
    SDL_Event e;
    while (SDL_PollEvent(&e))
        handle_sdl_event(lv, &e);
}
