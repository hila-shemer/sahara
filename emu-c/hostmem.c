#include "hostmem.h"

#include <sys/mman.h>

#include "rwc/status.h"

void *se_host_alloc(size_t bytes)
{
    void *p = mmap(NULL, bytes, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    RWC_ASSERT(p != MAP_FAILED);
    return p;
}

void se_host_free(void *p, size_t bytes)
{
    int rc = munmap(p, bytes);
    RWC_ASSERT(rc == 0);
}
