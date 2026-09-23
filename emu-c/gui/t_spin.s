# t_spin.s — sahara-serve guest that never sleeps (run-gui-tests): no
# WFI, no timer, just a branch to itself. Under --hz 0 the live loop
# then never waits in wait_fds' ppoll, the one place the stop signals
# used to be unblocked; SIGTERM must still end the session with the
# replay line.

        .org 0x1000
start:
        b start
