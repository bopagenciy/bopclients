"""Canonical responsive email templates for transactional notifications."""

import html
from typing import Tuple


def render_invitation_email(
    organization_name: str,
    role: str,
    invite_url: str,
    locale: str = "en",
    inviter_name: str = "",
) -> Tuple[str, str, str]:
    """Render subject, HTML body, and plain-text body for team invitations.

    Returns:
        Tuple of (subject, html_body, text_body).
    """
    clean_org = organization_name.strip() or "BopClients Organization"
    clean_role = role.strip().capitalize()
    escaped_org = html.escape(clean_org)
    escaped_role = html.escape(clean_role)
    escaped_url = html.escape(invite_url)
    escaped_inviter = html.escape(inviter_name.strip()) if inviter_name else ""

    norm_locale = (locale or "en").strip().lower()
    is_es = norm_locale.startswith("es")

    if is_es:
        role_map = {
            "Admin": "Administrador",
            "Member": "Miembro",
            "Viewer": "Lector",
        }
        translated_role = role_map.get(clean_role, clean_role)
        escaped_role = html.escape(translated_role)

        subject = f"Invitación para unirse a {clean_org} en BopClients"

        inviter_line = (
            f"<p style=\"margin: 0 0 16px; color: #4b5563; font-size: 15px; line-height: 24px;\"><strong>{escaped_inviter}</strong> le ha invitado a unirse al equipo.</p>"
            if escaped_inviter
            else ""
        )
        inviter_text = f"{inviter_name} le ha invitado a unirse al equipo.\n\n" if inviter_name else ""

        html_body = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(subject)}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0b0f19; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #111827;">
  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="table-layout: fixed;">
    <tr>
      <td align="center" style="padding: 40px 16px;">
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 560px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.3);">
          <!-- Header -->
          <tr>
            <td style="background-color: #0d121f; padding: 28px 32px; border-bottom: 2px solid #d4af37;">
              <table border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td>
                    <span style="color: #ffffff; font-weight: 800; font-size: 18px; letter-spacing: 1.5px;">BOP</span>
                    <span style="color: #d4af37; font-weight: 300; font-size: 18px; margin: 0 4px;">|</span>
                    <span style="color: #9ca3af; font-size: 13px; letter-spacing: 1px; text-transform: uppercase;">CLIENTS</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <!-- Body Content -->
          <tr>
            <td style="padding: 36px 32px 28px;">
              <h1 style="margin: 0 0 16px; color: #111827; font-size: 22px; font-weight: 700; line-height: 28px;">
                Invitación al equipo
              </h1>
              <p style="margin: 0 0 16px; color: #374151; font-size: 15px; line-height: 24px;">
                Ha sido invitado a unirse a la organización <strong>{escaped_org}</strong> con el rol de <strong>{escaped_role}</strong>.
              </p>
              {inviter_line}
              <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px 20px; margin: 24px 0;">
                <p style="margin: 0 0 6px; font-size: 13px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;">Detalles de la invitación</p>
                <p style="margin: 0 0 4px; font-size: 14px; color: #1f2937;"><strong>Organización:</strong> {escaped_org}</p>
                <p style="margin: 0 0 4px; font-size: 14px; color: #1f2937;"><strong>Rol asignado:</strong> {escaped_role}</p>
                <p style="margin: 0; font-size: 13px; color: #9ca3af;">Expira en 7 días.</p>
              </div>
              <!-- CTA Button -->
              <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 32px 0 20px;">
                <tr>
                  <td align="center">
                    <a href="{escaped_url}" target="_blank" style="display: inline-block; background-color: #d4af37; color: #0b0f19; font-size: 15px; font-weight: 700; text-decoration: none; padding: 14px 32px; border-radius: 6px; letter-spacing: 0.5px;">
                      Aceptar Invitación
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin: 24px 0 0; color: #9ca3af; font-size: 12px; line-height: 18px; text-align: center;">
                Si el botón no funciona, copie y pegue el siguiente enlace en su navegador:<br>
                <a href="{escaped_url}" style="color: #6b7280; word-break: break-all;">{escaped_url}</a>
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background-color: #f3f4f6; padding: 20px 32px; border-top: 1px solid #e5e7eb;">
              <p style="margin: 0; color: #6b7280; font-size: 12px; line-height: 18px; text-align: center;">
                Si no esperaba recibir esta invitación, puede ignorar este mensaje de forma segura.<br>
                &copy; BopClients. Todos los derechos reservados.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

        text_body = f"""BOP | CLIENTS
========================================
Invitación a {clean_org}

Ha sido invitado a unirse a la organización {clean_org} con el rol de {translated_role}.
{inviter_text}
Detalles de la invitación:
- Organización: {clean_org}
- Rol asignado: {translated_role}
- Validez: 7 días

Para aceptar la invitación y configurar su acceso, visite el siguiente enlace:
{invite_url}

Si no esperaba esta invitación, puede ignorar este mensaje.
========================================
© BopClients. Plataforma de Adquisición de Clientes.
"""

    else:
        subject = f"Invitation to join {clean_org} on BopClients"

        inviter_line = (
            f"<p style=\"margin: 0 0 16px; color: #4b5563; font-size: 15px; line-height: 24px;\"><strong>{escaped_inviter}</strong> has invited you to collaborate.</p>"
            if escaped_inviter
            else ""
        )
        inviter_text = f"{inviter_name} has invited you to collaborate.\n\n" if inviter_name else ""

        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(subject)}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0b0f19; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #111827;">
  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="table-layout: fixed;">
    <tr>
      <td align="center" style="padding: 40px 16px;">
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 560px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.3);">
          <!-- Header -->
          <tr>
            <td style="background-color: #0d121f; padding: 28px 32px; border-bottom: 2px solid #d4af37;">
              <table border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td>
                    <span style="color: #ffffff; font-weight: 800; font-size: 18px; letter-spacing: 1.5px;">BOP</span>
                    <span style="color: #d4af37; font-weight: 300; font-size: 18px; margin: 0 4px;">|</span>
                    <span style="color: #9ca3af; font-size: 13px; letter-spacing: 1px; text-transform: uppercase;">CLIENTS</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <!-- Body Content -->
          <tr>
            <td style="padding: 36px 32px 28px;">
              <h1 style="margin: 0 0 16px; color: #111827; font-size: 22px; font-weight: 700; line-height: 28px;">
                You've been invited to join a team
              </h1>
              <p style="margin: 0 0 16px; color: #374151; font-size: 15px; line-height: 24px;">
                You have been invited to join <strong>{escaped_org}</strong> as a <strong>{escaped_role}</strong>.
              </p>
              {inviter_line}
              <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px 20px; margin: 24px 0;">
                <p style="margin: 0 0 6px; font-size: 13px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;">Invitation Details</p>
                <p style="margin: 0 0 4px; font-size: 14px; color: #1f2937;"><strong>Organization:</strong> {escaped_org}</p>
                <p style="margin: 0 0 4px; font-size: 14px; color: #1f2937;"><strong>Assigned Role:</strong> {escaped_role}</p>
                <p style="margin: 0; font-size: 13px; color: #9ca3af;">This invitation expires in 7 days.</p>
              </div>
              <!-- CTA Button -->
              <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 32px 0 20px;">
                <tr>
                  <td align="center">
                    <a href="{escaped_url}" target="_blank" style="display: inline-block; background-color: #d4af37; color: #0b0f19; font-size: 15px; font-weight: 700; text-decoration: none; padding: 14px 32px; border-radius: 6px; letter-spacing: 0.5px;">
                      Accept Invitation
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin: 24px 0 0; color: #9ca3af; font-size: 12px; line-height: 18px; text-align: center;">
                If the button above does not work, copy and paste this link into your browser:<br>
                <a href="{escaped_url}" style="color: #6b7280; word-break: break-all;">{escaped_url}</a>
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="background-color: #f3f4f6; padding: 20px 32px; border-top: 1px solid #e5e7eb;">
              <p style="margin: 0; color: #6b7280; font-size: 12px; line-height: 18px; text-align: center;">
                If you were not expecting this invitation, you can safely ignore this email.<br>
                &copy; BopClients. All rights reserved.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

        text_body = f"""BOP | CLIENTS
========================================
Invitation to join {clean_org}

You have been invited to join {clean_org} as a {clean_role}.
{inviter_text}
Invitation Details:
- Organization: {clean_org}
- Assigned Role: {clean_role}
- Expiration: 7 days

To accept the invitation and access your organization, please visit:
{invite_url}

If you did not expect this invitation, you can safely ignore this email.
========================================
© BopClients. Autonomous Client Acquisition Platform.
"""

    return subject, html_body, text_body
