import os
import ssl
import smtplib
from email.message import EmailMessage

from core.i18n import tr


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


def _build_ssl_context():
    """Создаёт SSL-контекст с актуальным набором сертификатов certifi (при наличии)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def is_smtp_configured(app_settings):
    """Проверяет, заполнены ли обязательные параметры SMTP (независимо от автоотправки)."""
    smtp_host = app_settings.get("smtp_host", "").strip()
    smtp_port = str(app_settings.get("smtp_port", "")).strip()
    email_to = app_settings.get("email_to", "").strip()
    sender = (app_settings.get("email_from", "") or app_settings.get("smtp_user", "")).strip()
    if not (smtp_host and smtp_port.isdigit() and email_to and sender and "@" in email_to):
        return False
    port_num = int(smtp_port)
    return 1 <= port_num <= 65535


def is_email_auto_send_ready(app_settings):
    auto_enabled = str(app_settings.get("email_auto_send", "false")).lower() == "true"
    return bool(auto_enabled and is_smtp_configured(app_settings))


def split_files_into_email_batches(file_paths, max_bytes=MAX_EMAIL_ATTACHMENTS_BYTES):
    """Разбивает список файлов на порции так, чтобы суммарный размер вложений не превышал max_bytes."""
    batches = []
    current_batch = []
    current_size = 0

    for fp in file_paths:
        try:
            fsize = os.path.getsize(fp)
        except OSError:
            fsize = 0

        if current_batch and (current_size + fsize > max_bytes):
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
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    file_names = "\n".join(f"• {os.path.basename(p)}" for p in batch_files)
    msg.set_content(tr("converter.email_body", app=app_name, ver=app_version, files=file_names))

    for fp in batch_files:
        with open(fp, "rb") as f:
            data = f.read()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="octet-stream",
            filename=os.path.basename(fp)
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
