"""Regression from captured live outputs; regrading itself makes no API calls."""

import hashlib
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.improvement.regrade import regrade_captured_receipt
from app.runtime.hermes import APP_ROOT

CAPTURE = APP_ROOT / "docs/build/evidence/hosted-improvement-attempt.json"


@unittest.skipUnless(CAPTURE.exists(), "requires the retained local acceptance receipt")
class CapturedReceiptRegression(unittest.IsolatedAsyncioTestCase):
    async def test_offline_regrade_preserves_original_and_finds_no_gain(self):
        before = CAPTURE.read_bytes()
        denied = AsyncMock(
            side_effect=AssertionError("Offline diagnostic must not call a provider")
        )
        with (
            patch("httpx.AsyncClient.request", denied),
            patch("app.models.GenerativeModel.complete", denied),
        ):
            diagnostic = await regrade_captured_receipt(Path(CAPTURE))
        self.assertEqual(CAPTURE.read_bytes(), before)
        self.assertEqual(
            hashlib.sha256(before).hexdigest(),
            "594ed30f8d1ef55fb7418ba0fe9d75c4c32eb6a45d78fb64f561082c06477b8a",
        )
        self.assertFalse(diagnostic["fresh_inference"])
        self.assertFalse(diagnostic["promotion_permitted"])
        corrected = diagnostic["corrected_diagnostic"]
        self.assertEqual(corrected["reason"], "no_measured_improvement")
        self.assertEqual(corrected["metrics"]["baseline_correct"], 3)
        self.assertEqual(corrected["metrics"]["candidate_correct"], 3)
        self.assertEqual(
            corrected["metrics"]["baseline_tool_calls"],
            corrected["metrics"]["candidate_tool_calls"],
        )
        self.assertFalse(corrected["unseen_transfer_executed"])
        denied.assert_not_awaited()
