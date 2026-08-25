"""PUT /apps/<id>/env/<key> partial-update semantics at the route boundary.

The service door (EnvService.update_env_var) distinguishes "field absent"
(_UNSET, leave untouched) from "field explicitly null" (clear it). The route
must preserve that distinction for description: a JSON null clears, an omitted
key leaves the stored text alone.
"""
from app import db
from app.models import Application


def _seed_var(app):
    from app.services.env_service import EnvService
    from factories import make_application, make_user

    user = make_user(db, role='admin')
    application = make_application(db, name='env-api-app', user_id=user.id)
    EnvService.set_env_var(
        application.id, 'API_URL', 'https://api.example.test',
        description='where the API lives', user_id=user.id,
    )
    return application, user


def test_null_description_clears_but_omitted_leaves_it(app, client):
    from factories import headers_for

    with app.app_context():
        application, user = _seed_var(app)
        headers = headers_for(user)
        app_id = application.id

    # Omitting description entirely must not touch it.
    res = client.put(f'/api/v1/apps/{app_id}/env/API_URL',
                     json={'value': 'https://api2.example.test'},
                     headers=headers)
    assert res.status_code == 200
    assert res.get_json()['env_var']['description'] == 'where the API lives'

    # An explicit JSON null clears it.
    res = client.put(f'/api/v1/apps/{app_id}/env/API_URL',
                     json={'description': None},
                     headers=headers)
    assert res.status_code == 200
    assert res.get_json()['env_var']['description'] is None
