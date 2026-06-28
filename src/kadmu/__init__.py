"""Kadmu — a self-hosted personal cinema in a browser tab.

The backend used to be one big server.py; it's now this small package, split by
concern but still pure standard library, no build step. src/server.py is a thin
launcher that calls kadmu.app.main(). Module layout (dependencies point downward):

    const     constants, paths, locks, JSON helpers     (no intra-package deps)
    rt        mutable runtime flags set in app.main()    (no deps)
    accounts  SQLite users / sessions / per-user data    (const)
    media     ffmpeg: probe, thumbs, covers, subs, …     (const)
    store     config/roots, progress, My List, profiles  (const, rt, accounts)
    security  host/CSRF/auth, sessions, password         (const, rt, store)
    library   listing, search/index, file ops, trash     (const, rt, store, media)
    handler   the HTTP request Handler                   (everything above)
    app       server, browser launch, janitor, main()    (everything)
"""
