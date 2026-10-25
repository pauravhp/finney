The public landing now uses `/landing-v7.html`, the original standalone v7 export,
with navigation-only wiring in `/landing-v7-links.js`. The older adapted landing
assets below are retained but are no longer the public landing entry.

# Finney approved brand assets

Transferred from the owner-approved Organizer’s Desk v7.0 design. The landing
contains illustrative event data and an illustrated learning mechanism. Live
financial operations use the authenticated `/desk` application.

Albert Sans is bundled under the SIL Open Font License in `AlbertSans-OFL.txt`.
The receipt artwork, folder composition, and authored scroll timeline come from
the approved Finney design. The bundled GSAP 3.14.2 runtime retains its copyright
and license notice at the start of `landing.js` and `gsap.min.js`.

`landing.js` contains only the landing interaction and explanatory animation.
The source concept’s scripted agent, sample approvals and fake settlement code
are excluded. Primary actions open `/desk`; displayed sample financial figures
never enter the application database.
