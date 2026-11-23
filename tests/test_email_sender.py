import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.email_sender import (
    is_email_auto_send_ready,
    is_smtp_configured,
    send_converted_files_via_email,
    send_test_email,
    split_files_into_email_batches,
)


class TestEmailSender(unittest.TestCase):
    def _valid_settings(self, **overrides):
        base = {
            "email_auto_send": "true",
            "smtp_host": "smtp.example.com",
            "smtp_port": "465",
            "smtp_security": "ssl",
            "smtp_user": "user@example.com",
            "smtp_password": "secret",
            "email_from": "",
            "email_to": "reader@kindle.com",
        }
        base.update(overrides)
        return base

    def test_is_smtp_configured_and_auto_send_ready(self):
        st = self._valid_settings(email_auto_send="false")
        self.assertTrue(is_smtp_configured(st))
        self.assertFalse(is_email_auto_send_ready(st))

        st_on = self._valid_settings(email_auto_send="true")
        self.assertTrue(is_email_auto_send_ready(st_on))

        self.assertFalse(is_smtp_configured(self._valid_settings(smtp_host="")))
        self.assertFalse(is_smtp_configured(self._valid_settings(smtp_port="abc")))
        self.assertFalse(is_smtp_configured(self._valid_settings(smtp_port="0")))
        self.assertFalse(is_smtp_configured(self._valid_settings(smtp_port="70000")))
        self.assertFalse(is_smtp_configured(self._valid_settings(email_to="invalid")))

    def test_split_files_into_email_batches(self):
        with tempfile.TemporaryDirectory() as td:
            files = []
            for idx, sz in enumerate((600, 600, 500, 1200)):
                fp = os.path.join(td, f"book_{idx}.epub")
                with open(fp, "wb") as f:
                    f.write(b"x" * sz)
                files.append(fp)

            batches = split_files_into_email_batches(files, max_bytes=1000)
            self.assertEqual(len(batches), 4)
            batches_1300 = split_files_into_email_batches(files, max_bytes=1300)
            self.assertEqual(len(batches_1300), 3)
            self.assertEqual(len(batches_1300[0]), 2)

    def test_send_converted_files_via_email_ssl_and_progress(self):
        with tempfile.TemporaryDirectory() as td:
            f1 = os.path.join(td, "b1.epub")
            f2 = os.path.join(td, "b2.epub")
            with open(f1, "wb") as fh1:
                fh1.write(b"1" * 100)
            with open(f2, "wb") as fh2:
                fh2.write(b"2" * 100)

            mock_srv = MagicMock()
            progress_events = []

            with patch("core.email_sender.smtplib.SMTP_SSL") as mock_ssl:
                mock_ssl.return_value.__enter__.return_value = mock_srv
                send_converted_files_via_email(
                    self._valid_settings(),
                    [f1, f2],
                    "FBC GUI",
                    "2.5",
                    progress_callback=lambda pct, txt: progress_events.append((pct, txt)),
                )

            mock_srv.login.assert_called_once_with("user@example.com", "secret")
            mock_srv.send_message.assert_called_once()
            self.assertEqual(progress_events[-1][0], 100)

    def test_send_test_email_validation_and_starttls(self):
        with self.assertRaises(ValueError):
            send_test_email({}, "FBC GUI", "2.5")

        mock_srv = MagicMock()
        st = self._valid_settings(smtp_port="587", smtp_security="starttls")
        with patch("core.email_sender.smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_srv
            send_test_email(st, "FBC GUI", "2.5")

        mock_srv.starttls.assert_called_once()
        self.assertIn("context", mock_srv.starttls.call_args.kwargs)
        self.assertIsNotNone(mock_srv.starttls.call_args.kwargs["context"])
        mock_srv.login.assert_called_once_with("user@example.com", "secret")
        mock_srv.send_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
