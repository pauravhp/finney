import Script from "next/script";
import { landingHtml } from "@/components/landing-content";

/** The approved marketing illustration; operational controls live at /desk. */
export function Landing() {
  return (
    <>
      <link rel="stylesheet" href="/brand/landing.css" />
      <main
        className="marketing-root"
        dangerouslySetInnerHTML={{ __html: landingHtml }}
      />
      <dialog id="detail" aria-label="About Finney's learning loop">
        <button className="dialog-close" aria-label="Close">
          ×
        </button>
        <div id="detail-content" />
      </dialog>
      <Script src="/brand/landing.js" strategy="afterInteractive" />
    </>
  );
}
