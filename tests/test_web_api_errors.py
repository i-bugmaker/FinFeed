from finfeed.ui.web_fastapi.core.errors import ApiError, error_response


def test_error_response_uses_stable_contract():
    response = error_response(400, "INVALID_FILTER", "invalid filter", field="page")

    assert response.status_code == 400
    assert b'"success":false' in response.body
    assert b'"code":"INVALID_FILTER"' in response.body
    assert b'"field":"page"' in response.body


def test_api_error_preserves_transport_metadata():
    error = ApiError("missing item", status_code=404, code="NOT_FOUND")

    assert error.status_code == 404
    assert error.body.to_dict() == {"code": "NOT_FOUND", "message": "missing item"}
