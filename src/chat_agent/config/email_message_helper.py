import base64
import logging
import os
from typing import List, Optional, Dict, Any

import markdown
import requests

logger = logging.getLogger(__name__)


def format_markdown_to_email_html(md_text: str, timestamp: str = "", model_usage: Optional[str] = None) -> str:
    """Converts raw markdown text to inline-styled HTML suitable for insertion into Brevo email template."""
    logger.info("formatting markdown text for : ")
    if not md_text:
        md_text = "<p>No content available.</p>"

    # Convert markdown to basic HTML tags
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"]
    )

    # Inject inline styles into HTML tags for maximum email client compatibility
    html_body = html_body.replace("<table>",
                                  '<table style="border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 14px; text-align: left; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif;">')
    html_body = html_body.replace("<th>",
                                  '<th style="background-color: #eff6ff; color: #1e3a8a; font-weight: 600; padding: 10px 14px; border: 1px solid #cbd5e1;">')
    html_body = html_body.replace("<td>", '<td style="padding: 10px 14px; border: 1px solid #e2e8f0; color: #334155;">')
    html_body = html_body.replace("<h1>",
                                  '<h1 style="color: #1e3a8a; font-size: 22px; font-weight: 700; margin-top: 24px; margin-bottom: 12px; border-bottom: 2px solid #bfdbfe; padding-bottom: 6px;">')
    html_body = html_body.replace("<h2>",
                                  '<h2 style="color: #1e293b; font-size: 18px; font-weight: 600; margin-top: 20px; margin-bottom: 10px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px;">')
    html_body = html_body.replace("<h3>",
                                  '<h3 style="color: #334155; font-size: 16px; font-weight: 600; margin-top: 16px; margin-bottom: 8px;">')
    html_body = html_body.replace("<blockquote>",
                                  '<blockquote style="border-left: 4px solid #3b82f6; background-color: #eff6ff; padding: 12px 16px; margin: 16px 0; color: #1e3a8a; font-style: italic;">')
    html_body = html_body.replace("<pre><code>",
                                  '<pre style="background-color: #0f172a; color: #f8fafc; padding: 14px; border-radius: 6px; overflow-x: auto; font-family: Consolas, Monaco, monospace; font-size: 13px;"><code>')
    html_body = html_body.replace("<code>",
                                  '<code style="background-color: #f1f5f9; color: #0f172a; padding: 2px 6px; border-radius: 4px; font-family: Consolas, Monaco, monospace; font-size: 13px;">')
    html_body = html_body.replace("<hr />",
                                  '<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />')
    html_body = html_body.replace("<hr>", '<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />')

    if model_usage:
        html_body += f'<div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #e2e8f0; font-size: 15px; color: #64748b; text-align: left;">To build this response: {model_usage}</div>'

    if timestamp:
        html_body += f'<div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #64748b; text-align: right;">Analysis completed at: {timestamp}</div>'


    return html_body


def _render_email_template(subject_text: str, content_html: str, template_id: int = 1) -> str:
    """Renders local HTML template matching template_id with subject and content."""
    logger.info(" render_email_template started")

    template_filename = "task_execution_template_8.html" if template_id == 8 else "lite_task_email_template.html"

    possible_paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "ui", template_filename),
        os.path.join(os.path.dirname(__file__), "..", "ui", template_filename),
        os.path.join("ui", template_filename),
    ]
    template_str = None
    for p in possible_paths:
        abs_p = os.path.abspath(p)
        if os.path.exists(abs_p):
            try:
                with open(abs_p, "r", encoding="utf-8") as f:
                    template_str = f.read()
                break
            except Exception as e:
                logger.warning(f"Could not read template at {abs_p}: {e}")

    if not template_str:
        return content_html

    rendered = template_str.replace("{{ params.SUBJECT_TEXT }}", subject_text)
    rendered = rendered.replace("{{ params.CONTENT | safe }}", content_html)
    rendered = rendered.replace("{{ params.CONTENT|safe }}", content_html)
    rendered = rendered.replace("{{{ params.CONTENT }}}", content_html)
    rendered = rendered.replace("{{ params.CONTENT }}", content_html)
    return rendered


def send_email_with_brevo_template(
        to_emails: List[str],
        cc_emails: List[str],
        subject_text: str,
        content: str | Dict[str, Any],
        presigned_url: Optional[str] = None,
        file_name: str = "image.png",
        template_id: str = '1',
) -> bool:
    """Sends a transactional email using Brevo API, sending unescaped htmlContent rendered from local template."""

    api_key = os.getenv("BREVO_API_KEY")
    if not api_key:
        logger.error("BREVO_API_KEY is not set")
        return False

    template_id_str = os.getenv("TEMPLATE_ID", template_id)
    if not template_id_str:
        logging.error("template_id is not set")
        return False
    template_id_int: int = int(template_id_str)
    logger.info(f'using template id: {template_id_int}')

    # Auto-serialize content if it's a Pydantic model
    if hasattr(content, "model_dump"):
        content = content.model_dump()

    content_str = str(content) if not isinstance(content, str) else content

    # Render local HTML template directly to prevent Brevo template double-curly HTML escaping
    rendered_html = _render_email_template(subject_text, content_str, template_id_int)

    payload = {
        "templateId": template_id_int,
        "subject": subject_text,
        "htmlContent": rendered_html,
        "to": [{"email": email} for email in to_emails],
        "params": {"SUBJECT_TEXT": subject_text, "CONTENT": content_str},
    }

    if cc_emails:
        payload["cc"] = [{"email": email} for email in cc_emails]

    try:
        if presigned_url:
            response = requests.get(presigned_url)
            response.raise_for_status()

            b64_content = base64.b64encode(response.content).decode("utf-8")
            payload["attachment"] = [
                {"content": b64_content, "name": file_name}
            ]

        headers = {
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        }

        logger.info('initiaing email sending . . . ')
        api_url = "https://api.brevo.com/v3/smtp/email"
        api_response = requests.post(api_url, json=payload, headers=headers)

        if api_response.status_code in [201, 202]:
            logger.info("Template email successfully queued via Brevo API.")
            return True
        else:
            logger.error(f"Brevo API error: {api_response.text}")
            return False

    except Exception as e:
        logger.exception(f"Pipeline failure: {str(e)}")
        return False


def send_email_with_brevo_and_pdf_attachment(
        to_emails: List[str],
        cc_emails: List[str],
        subject_text: str,
        content: str | Dict[str, Any],
        presigned_url: Optional[str] = None,
        pdf_path: Optional[str] = None,
        file_name: str = "document.pdf",
        template_id: str = '1',
) -> bool:
    """Sends a transactional email using Brevo API, sending unescaped htmlContent rendered from local template with attached PDF."""

    api_key = os.getenv("BREVO_API_KEY")
    if not api_key:
        logger.error("BREVO_API_KEY is not set")
        return False

    template_id_str = os.getenv("TEMPLATE_ID", template_id)
    if not template_id_str:
        logging.error("template_id is not set")
        return False
    template_id_int: int = int(template_id_str)
    logger.info(f'using template id: {template_id_int}')

    # Auto-serialize content if it's a Pydantic model
    if hasattr(content, "model_dump"):
        content = content.model_dump()

    content_str = str(content) if not isinstance(content, str) else content

    # Render local HTML template directly to prevent Brevo template double-curly HTML escaping
    rendered_html = _render_email_template(subject_text, content_str, template_id_int)

    payload = {
        "templateId": template_id_int,
        "subject": subject_text,
        "htmlContent": rendered_html,
        "to": [{"email": email} for email in to_emails],
        "params": {"SUBJECT_TEXT": subject_text, "CONTENT": content_str},
    }

    if cc_emails:
        payload["cc"] = [{"email": email} for email in cc_emails]

    try:
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                b64_content = base64.b64encode(f.read()).decode("utf-8")
            payload["attachment"] = [
                {"content": b64_content, "name": file_name or os.path.basename(pdf_path)}
            ]
        elif presigned_url:
            response = requests.get(presigned_url)
            response.raise_for_status()

            b64_content = base64.b64encode(response.content).decode("utf-8")
            payload["attachment"] = [
                {"content": b64_content, "name": file_name}
            ]

        headers = {
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        }

        logger.info('initiating email sending . . . ')
        api_url = "https://api.brevo.com/v3/smtp/email"
        api_response = requests.post(api_url, json=payload, headers=headers)

        if api_response.status_code in [201, 202]:
            logger.info("Template email successfully queued via Brevo API.")
            return True
        else:
            logger.error(f"Brevo API error: {api_response.text}")
            return False

    except Exception as e:
        logger.exception(f"Pipeline failure: {str(e)}")
        return False
