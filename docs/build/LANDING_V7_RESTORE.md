# Standalone v7 landing

The public root serves the original `Finney-Organizers-Desk-v7.0.html` document
through a before-files rewrite, outside application CSS and React rendering.
Its embedded styles, fonts, artwork and animation are unchanged. The original
prototype scripts are retained with the document; normal navigation into their
scripted desk is redirected to the real application by a capture-phase handler.

Only navigation/startup changed: start on landing, ignore prototype state fixtures,
point the learning-source link at GitHub main, and load destination wiring. Try
Finney and companion actions open `/desk?demo=guided`; report/budget controls open
the corresponding real app sections. Existing authenticated/OAuth root links still
redirect to the app. The previous React landing adapter is no longer served.

The reference and served document matched section geometry and typography at
1440, 768 and 390 pixels. Four desktop/mobile navigation checks and the production
build/TypeScript passed. No worker, seed, model or financial operation changed.
