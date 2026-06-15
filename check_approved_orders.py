#!/usr/bin/env python3
import os
import json
import base64
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

TINY_TOKEN         = os.environ['TINY_TOKEN']
GMAIL_USER         = os.environ['GMAIL_USER']
GMAIL_FROM         = os.environ.get('GMAIL_FROM', os.environ['GMAIL_USER'])
GMAIL_APP_PASSWORD = os.environ['GMAIL_APP_PASSWORD']
ALERT_EMAILS       = [e.strip() for e in os.environ['ALERT_EMAILS_APROVADO'].split(',')]
THRESHOLD          = int(os.environ.get('THRESHOLD_APROVADO', '55'))
FORCE_TEST         = os.environ.get('FORCE_TEST', 'false').lower() == 'true'
GITHUB_TOKEN       = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPO        = os.environ.get('GITHUB_REPOSITORY', '')

STATE_FILE = 'state_aprovado.json'


def get_approved_orders_count():
    url = "https://api.tiny.com.br/api2/pedidos.pesquisa.php"
    total = 0
    page = 1

    while True:
        params = {
            'token': TINY_TOKEN,
            'formato': 'json',
            'situacao': 'aprovado',
            'pagina': page,
        }
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()

        retorno = data.get('retorno', {})
        if retorno.get('status') != 'OK':
            break

        pedidos = retorno.get('pedidos', [])
        if not pedidos:
            break

        total += len(pedidos)

        numero_paginas = int(retorno.get('numero_paginas', 1))
        if page >= numero_paginas:
            break
        page += 1

    return total


def get_state():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return {'was_above': False}, None

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATE_FILE}"
    headers = {
        'Authorization': f'Bearer {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }
    r = requests.get(url, headers=headers)

    if r.status_code == 404:
        return {'was_above': False}, None
    if r.status_code != 200:
        print(f"Aviso: não foi possível ler o estado ({r.status_code})")
        return {'was_above': False}, None

    data = r.json()
    content = base64.b64decode(data['content']).decode()
    return json.loads(content), data['sha']


def save_state(state, sha=None):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATE_FILE}"
    headers = {
        'Authorization': f'Bearer {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }
    content = base64.b64encode(json.dumps(state, indent=2).encode()).decode()
    payload = {
        'message': f'chore: atualiza estado aprovados [{datetime.now().strftime("%Y-%m-%d %H:%M")}]',
        'content': content,
    }
    if sha:
        payload['sha'] = sha

    r = requests.put(url, headers=headers, json=payload)
    if r.status_code not in (200, 201):
        print(f"Aviso: não foi possível salvar estado ({r.status_code})")


def send_alert_email(count):
    msg = MIMEMultipart('alternative')
    msg['From']    = GMAIL_FROM
    msg['To']      = ', '.join(ALERT_EMAILS)
    msg['Subject'] = f"⚠️ Alerta 4climb — {count} pedidos APROVADOS em aberto"

    now = datetime.now().strftime('%d/%m/%Y às %H:%M')

    text = f"""Alerta de pedidos aprovados — 4climb

Existem {count} pedidos com status APROVADO no Tiny.
Verificado em: {now}

Acesse o Tiny para processar os pedidos.
"""

    html = f"""<html><body style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px">
<h2 style="color:#e65100">⚠️ Alerta de Pedidos Aprovados — 4climb</h2>
<p>Existem <strong style="font-size:1.4em;color:#e65100">{count}</strong> pedidos com status <strong>APROVADO</strong> no Tiny.</p>
<p style="color:#666;font-size:.9em">Verificado em: {now}</p>
<p style="margin-top:24px">
  <a href="https://erp.tiny.com.br" style="background:#1976d2;color:white;padding:12px 24px;text-decoration:none;border-radius:4px;font-weight:bold">
    Acessar Tiny →
  </a>
</p>
</body></html>"""

    msg.attach(MIMEText(text, 'plain'))
    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, ALERT_EMAILS, msg.as_string())

    print(f"E-mail de alerta enviado para: {', '.join(ALERT_EMAILS)}")


def main():
    print(f"Verificando pedidos aprovados... [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")

    count = get_approved_orders_count()
    print(f"Pedidos aprovados: {count} (limite: {THRESHOLD})")

    state, sha = get_state()
    was_above = state.get('was_above', False)
    is_above  = count >= THRESHOLD

    if FORCE_TEST:
        print("Modo teste ativado — enviando e-mail independente do estado.")
        send_alert_email(count)
        return

    if is_above and not was_above:
        print("Limite atingido! Enviando alerta...")
        send_alert_email(count)
        save_state({
            'was_above': True,
            'count_at_alert': count,
            'alerted_at': datetime.now().isoformat(),
        }, sha)

    elif not is_above and was_above:
        print("Voltou abaixo do limite. Resetando estado.")
        save_state({
            'was_above': False,
            'count': count,
            'reset_at': datetime.now().isoformat(),
        }, sha)

    else:
        print(f"Sem mudança de estado (acima={is_above})")


if __name__ == '__main__':
    main()
