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

    def test_smtp_security_validation_and_batch_cancel(self):
        import threading
        from core.email_sender import EmailCancelledError

        with self.assertRaises(ValueError):
            send_test_email(self._valid_settings(smtp_security="bogus"), "FBC GUI", "2.9.1")

        # 'tls' нормализуется в starttls
        mock_srv = MagicMock()
        with patch("core.email_sender.smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_srv
            send_test_email(self._valid_settings(smtp_port="587", smtp_security="tls"), "FBC GUI", "2.9.1")
        mock_srv.starttls.assert_called_once()

        # Отмена между пакетами отправки
        with tempfile.TemporaryDirectory() as td:
            f1 = os.path.join(td, "b1.epub")
            f2 = os.path.join(td, "b2.epub")
            for fp in (f1, f2):
                with open(fp, "wb") as fh:
                    fh.write(b"x" * 100)

            cancel_ev = threading.Event()
            sent_count = 0

            def _send_and_cancel(_msg):
                nonlocal sent_count
                sent_count += 1
                cancel_ev.set()

            srv = MagicMock()
            srv.send_message.side_effect = _send_and_cancel
            with patch("core.email_sender.smtplib.SMTP_SSL") as mock_ssl, patch(
                "core.email_sender.split_files_into_email_batches", return_value=[[f1], [f2]]
            ):
                mock_ssl.return_value.__enter__.return_value = srv
                with self.assertRaises(EmailCancelledError):
                    send_converted_files_via_email(
                        self._valid_settings(),
                        [f1, f2],
                        "FBC GUI",
                        "2.9.1",
                        cancel_event=cancel_ev,
                    )
            self.assertEqual(sent_count, 1)

    def test_oversized_single_attachment_rejected_before_smtp_and_none_warns(self):
        from core.email_sender import find_oversized_email_files

        with tempfile.TemporaryDirectory() as td:
            big_fp = os.path.join(td, "huge.epub")
            with open(big_fp, "wb") as fh:
                fh.write(b"x" * 2048)

            self.assertEqual(len(find_oversized_email_files([big_fp], max_bytes=1024)), 1)
            with patch("core.email_sender.MAX_EMAIL_ATTACHMENTS_BYTES", 1024), \
                 patch("core.email_sender.smtplib.SMTP_SSL") as mock_ssl:
                with self.assertRaises(ValueError) as ctx:
                    send_converted_files_via_email(self._valid_settings(), [big_fp], "FBC GUI", "2.11")
            self.assertIn("huge.epub", str(ctx.exception))
            mock_ssl.assert_not_called()

        mock_srv = MagicMock()
        with patch("core.email_sender.smtplib.SMTP") as mock_smtp, \
             patch("core.email_sender.logger.warning") as warn_mock:
            mock_smtp.return_value.__enter__.return_value = mock_srv
            send_test_email(self._valid_settings(smtp_port="25", smtp_security="none"), "FBC GUI", "2.11")
        warn_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
