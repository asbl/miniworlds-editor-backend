from .conftest import auth, create_project, student_token


def test_protocol_metadata_and_preflight(client):
    r = client.get('/api/compatibility')
    assert r.status_code == 200
    assert r.json()['component'] == 'miniworlds-editor-backend'
    assert r.json()['api'] == {'min': 1, 'max': 1}
    r = client.options('/api/play/project', headers={'Origin': 'https://editor.opencoding.de', 'Access-Control-Request-Method':'GET', 'Access-Control-Request-Headers':'x-miniworlds-api,authorization'})
    assert r.status_code == 200
    assert r.headers['access-control-allow-origin'] == 'https://editor.opencoding.de'


def test_incompatible_editor_cannot_modify_project(client, teacher_csrf):
    p = create_project(client, teacher_csrf)[0]
    token = student_token(client, p['code'])
    headers = {**auth(token), 'X-Miniworlds-API':'2'}
    r = client.put('/api/play/save', headers=headers, json={'source':'must not persist'})
    assert r.status_code == 426
    assert 'aktualisieren' in r.json()['detail']
    assert client.get('/api/play/project', headers=auth(token)).json()['revision'] == 0
    assert client.get('/api/play/project', headers={**auth(token), 'X-Miniworlds-API':'1'}).status_code == 200


def test_preview_requires_teacher_and_has_no_private_payload_in_html(client, client2, teacher_csrf):
    p = create_project(client, teacher_csrf)[0]
    token = student_token(client, p['code'])
    client.put('/api/play/save', headers=auth(token), json={'source':'PRIVATE_SOURCE'})
    assert client2.get(f'/player?teacher={p["id"]}').status_code == 401
    page = client.get(f'/player?teacher={p["id"]}')
    assert page.status_code == 200
    assert 'PRIVATE_SOURCE' not in page.text and token not in page.text
    assert 'frame-src https://editor.opencoding.de' in page.headers['content-security-policy']
    assert client.get('/player?teacher=invalid').status_code == 422


def test_oversized_version_header_is_rejected_without_parsing_an_unbounded_integer(client):
    assert client.get('/api/compatibility', headers={'X-Miniworlds-API':'9'*5000}).status_code == 426
