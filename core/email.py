import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()


def send_email(to: str, subject: str, html: str):
    """Envía un email HTML usando el SMTP de Hostinger."""
    smtp_host = os.getenv("SMTP_HOST", "smtp.hostinger.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")

    if not smtp_user or not smtp_pass:
        raise ValueError("SMTP no configurado")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"RoadmapIA <{smtp_user}>"
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to, msg.as_string())


def reset_password_email(nombre: str, email: str, reset_url: str) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;background:#f9f9f9;padding:32px;border-radius:10px">
      <div style="text-align:center;margin-bottom:24px">
        <span style="font-size:1.4rem;font-weight:900;color:#7c6fff">🧠 RoadmapIA</span>
      </div>
      <h2 style="color:#1a1033;margin-bottom:8px">Restablecer contraseña</h2>
      <p style="color:#555;margin-bottom:20px">Hola {nombre}, hemos recibido una solicitud para restablecer tu contraseña.</p>
      <div style="text-align:center;margin:28px 0">
        <a href="{reset_url}" style="background:linear-gradient(135deg,#7c6fff,#4f8ef7);color:#fff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:700;font-size:1rem">
          Restablecer contraseña →
        </a>
      </div>
      <p style="color:#888;font-size:13px">Este enlace expira en <strong>1 hora</strong>. Si no solicitaste esto, ignora este email.</p>
      <hr style="border:1px solid #eee;margin:20px 0">
      <p style="color:#aaa;font-size:12px;text-align:center">RoadmapIA · roadmapia.com</p>
    </div>
    """
