import os
import smtplib
from email.message import EmailMessage

from core.i18n import tr
from core.logger import get_logger
from core.updater import _build_ssl_context

logger = get_logger("email_sender")

MAX_EMAIL_ATTACHMENTS_BYTES = 20 * 1024 * 1024  # 20 МБ на одно письмо (запас под base64/MIME)


class EmailCancelledError(Exception):
    """Исключение при отмене отправки писем пользователем."""


def _normalize_smtp_security(raw_value):
    val = str(raw_value or "ssl").strip().lower()
    if val == "tls":
        return "starttls"
    if val in ("ssl", "starttls", "none"):
        return val
    raise ValueError(f"Unsupported smtp_security value: {raw_value!r}")


def _has_unsafe_header_chars(value):
    return any(ch in str(value or "") for ch in ("\r", "\n", "\x00"))


def _validate_email_header_value(label, value):
    raw = str(value or "")
    if _has_unsafe_header_chars(raw):
        raise ValueError(f"Invalid control character in {label}")
    return raw.strip()


def is_smtp_configured(app_settings):
    """Проверяет, заполнены ли обязательные параметры SMTP (независимо от автоотправки)."""
    raw_host = app_settings.get("smtp_host", "")
    raw_to = app_settings.get("email_to", "")
    raw_from = app_settings.get("email_from", "")
    raw_user = app_settings.get("smtp_user", "")
    if any(_has_unsafe_header_chars(v) for v in (raw_host, raw_to, raw_from, raw_user)):
        return False
    smtp_host = str(raw_host).strip()
    smtp_port = str(app_settings.get("smtp_port", "")).strip()
    email_to = str(raw_to).strip()
    sender = (str(raw_from) or str(raw_user)).strip()
    if not (smtp_host and smtp_port.isdigit() and email_to and sender and "@" in email_to):
        return False
    port_num = int(smtp_port)
    return 1 <= port_num <= 65535


def is_email_auto_send_ready(app_settings):
    auto_enabled = str(app_settings.get("email_auto_send", "false")).lower() == "true"
    return bool(auto_enabled and is_smtp_configured(app_settings))


def find_oversized_email_files(file_paths, max_bytes=None):
    """Возвращает список (filepath, size_bytes) для файлов, чей размер превышает max_bytes."""
    limit = MAX_EMAIL_ATTACHMENTS_BYTES if max_bytes is None else max_bytes
    oversized = []
    for fp in (file_paths or []):
        try:
            fsize = os.path.getsize(fp)
        except OSError:
            continue
        if fsize > limit:
            oversized.append((fp, fsize))
    return oversized


def split_files_into_email_batches(file_paths, max_bytes=None, reject_oversized=False):
    """Разбивает список файлов на порции так, чтобы суммарный размер вложений не превышал max_bytes."""
    limit = MAX_EMAIL_ATTACHMENTS_BYTES if max_bytes is None else max_bytes
    if reject_oversized:
        oversized = find_oversized_email_files(file_paths, max_bytes=limit)
        if oversized:
            names = ", ".join(f"{os.path.basename(p)} ({sz / (1024 * 1024):.1f} MB)" for p, sz in oversized)
            limit_mb = limit / (1024 * 1024)
            raise ValueError(f"Attachment exceeds email size limit ({limit_mb:.0f} MB): {names}")

    batches = []
    current_batch = []
    current_size = 0

    for fp in file_paths:
        try:
            fsize = os.path.getsize(fp)
        except OSError:
            fsize = 0

        if current_batch and (current_size + fsize > limit):
            batches.append(current_batch)
            current_batch = [fp]
            current_size = fsize
        else:
            current_batch.append(fp)
            current_size += fsize

    if current_batch:
        batches.append(current_batch)
    return batches


def _build_email_message(email_from, email_to, subject, batch_files, app_name, app_version):
    safe_from = _validate_email_header_value("From", email_from)
    safe_to = _validate_email_header_value("To", email_to)
    safe_subject = _validate_email_header_value("Subject", subject)
    msg = EmailMessage()
    msg["Subject"] = safe_subject
    msg["From"] = safe_from
    msg["To"] = safe_to
    file_names = "\n".join(f"• {os.path.basename(p)}" for p in batch_files)
    msg.set_content(tr("converter.email_body", app=app_name, ver=app_version, files=file_names))

    for fp in batch_files:
        with open(fp, "rb") as f:
            data = f.read()
        safe_fname = os.path.basename(fp).replace("\r", "").replace("\n", "").replace("\x00", "")
        msg.add_attachment(
            data,
            maintype="application",
            subtype="octet-stream",
            filename=safe_fname or "book.bin"
        )
    return msg


def send_converted_files_via_email(
    app_settings, file_paths, app_name, app_version, progress_callback=None, cancel_event=None
):
    if not file_paths:
        return
    if cancel_event is not None and cancel_event.is_set():
        raise EmailCancelledError("Email sending cancelled")
    if not is_smtp_configured(app_settings):
        raise ValueError(tr("settings.email_test_incomplete"))

    smtp_host = app_settings.get("smtp_host", "").strip()
    smtp_port = int(str(app_settings.get("smtp_port", "465")).strip())
    smtp_sec = _normalize_smtp_security(app_settings.get("smtp_security", "ssl"))
    smtp_user = app_settings.get("smtp_user", "").strip()
    smtp_password = app_settings.get("smtp_password", "")
    email_from = (app_settings.get("email_from", "") or smtp_user).strip()
    email_to = app_settings.get("email_to", "").strip()

    if smtp_sec == "none" and smtp_user:
        logger.warning(
            "SMTP-авторизация для %s:%s выполняется без шифрования (smtp_security='none')",
            smtp_host,
            smtp_port,
        )

    oversized = find_oversized_email_files(file_paths)
    if oversized:
        names = ", ".join(f"{os.path.basename(p)} ({sz / (1024 * 1024):.1f} MB)" for p, sz in oversized)
        limit_mb = MAX_EMAIL_ATTACHMENTS_BYTES / (1024 * 1024)
        raise ValueError(f"Attachment exceeds email size limit ({limit_mb:.0f} MB): {names}")

    if progress_callback:
        progress_callback(15, tr("converter.progress_email_prep"))

    batches = split_files_into_email_batches(file_paths)
    total_batches = len(batches)
    base_subject = tr("converter.email_subject", app=app_name, count=len(file_paths))

    if cancel_event is not None and cancel_event.is_set():
        raise EmailCancelledError("Email sending cancelled")
    if progress_callback:
        progress_callback(45, tr("converter.progress_email_connect", host=smtp_host))

    def _send_all(server):
        if smtp_user:
            server.login(smtp_user, smtp_password)
        for idx, batch in enumerate(batches, start=1):
            if cancel_event is not None and cancel_event.is_set():
                raise EmailCancelledError("Email sending cancelled")
            subj = f"{base_subject} ({idx}/{total_batches})" if total_batches > 1 else base_subject
            msg = _build_email_message(email_from, email_to, subj, batch, app_name, app_version)
            if progress_callback:
                pct = 50 + int(45 * (idx - 1) / max(1, total_batches))
                progress_callback(pct, tr("converter.progress_email_send", email=email_to))
            server.send_message(msg)

    ssl_ctx = _build_ssl_context() if smtp_sec in ("ssl", "starttls") else None
    if smtp_sec == "ssl":
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30, context=ssl_ctx) as server:
            _send_all(server)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            if smtp_sec == "starttls":
                server.starttls(context=ssl_ctx)
                server.ehlo()
            _send_all(server)

    if progress_callback:
        progress_callback(100, tr("converter.progress_email_done"))


def send_test_email(app_settings, app_name, app_version):
    """Отправляет короткое тестовое письмо для проверки параметров SMTP."""
    if not is_smtp_configured(app_settings):
        raise ValueError(tr("settings.email_test_incomplete"))

    smtp_host = app_settings.get("smtp_host", "").strip()
    smtp_port = int(str(app_settings.get("smtp_port", "465")).strip())
    smtp_sec = _normalize_smtp_security(app_settings.get("smtp_security", "ssl"))
    smtp_user = app_settings.get("smtp_user", "").strip()
    smtp_password = app_settings.get("smtp_password", "")
    email_from = (app_settings.get("email_from", "") or smtp_user).strip()
    email_to = app_settings.get("email_to", "").strip()

    if smtp_sec == "none" and smtp_user:
        logger.warning(
            "SMTP-авторизация для %s:%s выполняется без шифрования (smtp_security='none')",
            smtp_host,
            smtp_port,
        )

    msg = EmailMessage()
    msg["Subject"] = tr("settings.email_test_subject", app=app_name)
    msg["From"] = email_from
    msg["To"] = email_to
    msg.set_content(
        tr(
            "settings.email_test_body",
            app=app_name,
            ver=app_version,
            host=smtp_host,
            port=smtp_port,
        )
    )

    def _dispatch(server):
        if smtp_user:
            server.login(smtp_user, smtp_password)
        server.send_message(msg)

    ssl_ctx = _build_ssl_context() if smtp_sec in ("ssl", "starttls") else None
    if smtp_sec == "ssl":
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20, context=ssl_ctx) as server:
            _dispatch(server)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.ehlo()
            if smtp_sec == "starttls":
                server.starttls(context=ssl_ctx)
                server.ehlo()
            _dispatch(server)
