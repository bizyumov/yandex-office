"""Synthetic sender protocol tests; never connect to a real mailbox."""
import imaplib
import smtplib
from email import policy
from email.parser import BytesParser
from unittest.mock import MagicMock, patch

import pytest

from test_send_email import build_sender, make_ctx
import send_email as module
from common.api import method_auth


def transport(sender):
    smtp = MagicMock()
    smtp.sendmail.return_value = {}
    imap = MagicMock()
    imap.select.return_value = ('OK', [b'0'])
    imap.append.return_value = ('OK', [b'[APPENDUID 10 42] done'])
    def fetch(*args):
        payload = imap.append.call_args.args[3]
        return 'OK', [b'42', (b'42 (UID 42 BODY[]', b'Received: by example.com\r\n' + payload), b')']
    imap.uid.side_effect = fetch
    sender._connect_smtp = MagicMock(return_value=module.SmtpSendResult(smtp, 'sender@example.com'))
    sender._connect_sent = MagicMock(return_value=(imap, 'sender@example.com'))
    return smtp, imap


def test_attachment_bytes_headers_and_verified_sent(tmp_path):
    sender = build_sender()
    smtp, imap = transport(sender)
    a = tmp_path / 'report.pdf'; a.write_bytes(b'%PDF-1.0\x00\xff')
    b = tmp_path / '\u6587\u4ef6.unknownxyz'; b.write_bytes(b'\x00data')
    result = sender.send(to='a@example.com', cc='c@example.com', bcc='hidden@example.com',
                         reply_to='reply@example.com', subject='Example', body='<p>Body</p>',
                         content_type='html', attachments=[a, str(b)], save_sent=True)
    raw = smtp.sendmail.call_args.args[2]
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    parts = list(msg.iter_attachments())
    assert [(p.get_filename(), p.get_payload(decode=True)) for p in parts] == [(a.name, a.read_bytes()), (b.name, b.read_bytes())]
    assert parts[0].get_content_type() == 'application/pdf'
    assert parts[1].get_content_type() == 'application/octet-stream'
    assert msg.get_body().get_content_type() == 'text/html'
    assert msg['Date'] and msg['Message-ID'] == result['message_id']
    assert msg['Reply-To'] == 'reply@example.com' and 'Bcc' not in msg
    assert smtp.sendmail.call_args.args[1] == ['a@example.com', 'c@example.com', 'hidden@example.com']
    assert imap.append.call_args.args[0] == 'Sent'
    assert imap.append.call_args.args[3] == raw
    assert result['sent_copy'] == {'status': 'verified', 'folder': 'Sent', 'uid': '42'}
    assert result['smtp_status'] == 'accepted'
    assert smtp.sendmail.call_count == imap.append.call_count == 1
    assert all(c.args[0] == 'Sent' for c in imap.select.call_args_list)
    smtp.quit.assert_called_once(); imap.logout.assert_called_once()


@pytest.mark.parametrize('kind', ['missing', 'directory'])
def test_invalid_attachment_before_network(tmp_path, kind):
    sender = build_sender(); smtp, imap = transport(sender)
    target = tmp_path / 'missing' if kind == 'missing' else tmp_path
    with pytest.raises(OSError):
        sender.send(to='a@example.com', subject='x', body='y', attachments=[target], save_sent=True)
    sender._connect_smtp.assert_not_called(); sender._connect_sent.assert_not_called()


@pytest.mark.parametrize('fault', ['auth', 'identity', 'folder'])
def test_sent_preflight_blocks_smtp(fault):
    sender = build_sender(); smtp, imap = transport(sender)
    if fault == 'auth': sender._connect_sent.side_effect = RuntimeError('auth failed')
    if fault == 'identity': sender._connect_sent.return_value = (imap, 'other@example.com')
    if fault == 'folder': imap.select.return_value = ('NO', [b'not found'])
    with pytest.raises(RuntimeError):
        sender.send(to='a@example.com', subject='x', body='y', save_sent=True)
    smtp.sendmail.assert_not_called(); imap.append.assert_not_called()
    smtp.quit.assert_called_once()
    if fault != 'auth': imap.logout.assert_called_once()


@pytest.mark.parametrize('fault', ['append_no', 'append_error', 'missing_uid', 'fetch_error', 'wrong_content'])
def test_archival_failure_never_resends(fault):
    sender = build_sender(); smtp, imap = transport(sender)
    if fault == 'append_no': imap.append.return_value = ('NO', [b'quota'])
    if fault == 'append_error': imap.append.side_effect = imaplib.IMAP4.abort('lost')
    if fault == 'missing_uid': imap.append.return_value = ('OK', [b'done'])
    if fault == 'fetch_error': imap.uid.side_effect = imaplib.IMAP4.abort('lost')
    if fault == 'wrong_content': imap.uid.side_effect = None; imap.uid.return_value = ('OK', [(b'42', b'Subject: wrong\r\n\r\nx')])
    result = sender.send(to='a@example.com', subject='x', body='y', save_sent=True)
    assert result['status'] == 'partial' and result['smtp_status'] == 'accepted'
    assert result['sent_copy']['status'] in ('failed', 'unverified')
    assert result['retry_safe'] is False
    assert smtp.sendmail.call_count == imap.append.call_count == 1
    smtp.quit.assert_called_once(); imap.logout.assert_called_once()


@pytest.mark.parametrize('fault', ['partial', 'refused', 'unknown'])
def test_smtp_outcomes(fault):
    sender = build_sender(); smtp, imap = transport(sender)
    if fault == 'partial': smtp.sendmail.return_value = {'b@example.com': (550, b'no')}
    if fault == 'refused': smtp.sendmail.side_effect = smtplib.SMTPRecipientsRefused({'a@example.com': (550, b'no')})
    if fault == 'unknown': smtp.sendmail.side_effect = smtplib.SMTPServerDisconnected('lost')
    result = sender.send(to=['a@example.com', 'b@example.com'], subject='x', body='y', save_sent=True)
    assert result['smtp_status'] == fault
    assert result['status'] != 'sent' and result['retry_safe'] is False
    assert imap.append.call_count == (1 if fault == 'partial' else 0)
    assert smtp.sendmail.call_count == 1


def test_save_sent_opt_in_and_cli_wiring(tmp_path, capsys):
    sender = build_sender(); smtp, imap = transport(sender)
    r = sender.send(to='a@example.com', subject='x', body='y')
    assert r['sent_copy']['status'] == 'not_requested'
    sender._connect_sent.assert_not_called()
    with patch.object(module.EmailSender, '__init__', lambda *a, **kw: None), patch.object(module.EmailSender, 'send', return_value={**r, 'status': 'partial'}) as send:
        code = module.main(['--to','a@example.com','--subject','x','--body','y','--attachment','one.pdf','--attachment','two.bin','--save-sent','--format','json'])
    assert code == 2
    assert send.call_args.kwargs['attachments'] == ['one.pdf', 'two.bin']
    assert send.call_args.kwargs['save_sent'] is True
    assert 'partial' in capsys.readouterr().out


def test_sent_auth_requires_full_scope_and_uses_tls():
    assert method_auth(module.EmailSender._connect_sent_oauth2).one_of == ('mail:imap_full',)
    sender = build_sender(); ctx = make_ctx()
    with patch.object(module.imaplib, 'IMAP4_SSL') as cls:
        conn, identity = sender._connect_sent_oauth2.__wrapped__(sender, ctx)
    assert conn is cls.return_value and identity == 'sender@example.com'
    assert cls.call_args.kwargs['ssl_context'].verify_mode != 0
    mechanism, callback = conn.authenticate.call_args.args
    assert mechanism == 'XOAUTH2' and b'user=sender@example.com' in callback(b'')
