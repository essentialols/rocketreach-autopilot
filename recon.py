#!/usr/bin/env python3
"""
RocketReach API recon -- documents the internal endpoints discovered
by reverse-engineering the Angular frontend.

This module maps the internal API surface extracted from the JS bundle
at https://static.rocketreach.co/bundles/js/output.*.js
"""

# All endpoints discovered via static analysis of the Angular bundle.
# These are called by the SPA via $http.post / $http.get internally.

ENDPOINTS = {
    "signup": {
        "method": "POST",
        "url": "/v1/signup",
        "content_type": "application/x-www-form-urlencoded; charset=UTF-8",
        "fields": {
            "csrfmiddlewaretoken": "validation_token cookie value",
            "name": "Full name",
            "login": "Email address",
            "password": "Password (min 8, max 128 chars)",
            "agreeTerms": "true",
            "force_phone": "false",
            "g-recaptcha-response": "reCAPTCHA v3 token",
        },
        "auth": "CSRF cookie (validation_token) + X-CSRFToken header",
        "captcha": {
            "type": "reCAPTCHA v3 (invisible)",
            "site_key": "6Le8JXkUAAAAABWqhg7ud4UjL6yCBDirQhWh5CHD",
            "action": "signup",
        },
        "response_codes": {
            200: "Success -- account created",
            403: "Account created but phone verification required (error_code=205)",
            422: "Validation errors (captcha, duplicate email, etc.)",
        },
        "notes": [
            "Angular uses $httpParamSerializerJQLike -- standard form encoding",
            "Does NOT accept JSON body despite returning JSON",
            "CSRF token comes from validation_token cookie set on GET /signup",
            "RecaptchaService.execute('signup') is called before form submit",
        ],
    },
    "user_info": {
        "method": "GET",
        "url": "/v1/user",
        "auth": "Session cookie",
    },
    "resend_verification": {
        "method": "POST",
        "url": "/v1/resendVerification",
        "auth": "Session cookie",
    },
    "generate_email": {
        "method": "POST",
        "url": "/v1/generateEmail",
        "auth": "Session cookie + API key",
    },
    "send_email": {
        "method": "POST",
        "url": "/v1/sendEmail",
        "auth": "Session cookie + API key",
    },
    "person_lookup": {
        "method": "POST",
        "url": "/v1/profiles",
        "auth": "Session cookie + API key",
    },
    "start_trial": {
        "method": "POST",
        "url": "/v1/startTrial",
        "auth": "Session cookie",
    },
    "create_order": {
        "method": "POST",
        "url": "/v1/services/createOrder",
        "auth": "Session cookie",
    },
    "api_key": {
        "method": "POST",
        "url": "/api/account/key",
        "auth": "Session cookie",
    },
    "deactivate": {
        "method": "POST",
        "url": "/v1/deactivate/",
        "auth": "Session cookie",
    },
}

# Form fields extracted from the signup page DOM
SIGNUP_FORM = {
    "form_action": "Angular SPA (no HTML form action, submitted via XHR)",
    "fields": [
        {"selector": "#name", "type": "text", "ng_model": "createAccountFormData.name", "placeholder": "Full Name"},
        {"selector": "#email", "type": "email", "ng_model": "$parent.createAccountFormData.login", "placeholder": "Business Email"},
        {"selector": "#password", "type": "password", "ng_model": "createAccountFormData.password", "placeholder": "Password"},
        {"selector": "#terms", "type": "checkbox", "ng_model": "createAccountFormData.agreeTerms", "pre_checked": True},
    ],
    "csrf": {
        "cookie_name": "validation_token",
        "hidden_field": "csrfmiddlewaretoken",
    },
    "captcha": {
        "provider": "Google reCAPTCHA v3",
        "type": "invisible (score-based)",
        "site_key": "6Le8JXkUAAAAABWqhg7ud4UjL6yCBDirQhWh5CHD",
        "action": "signup",
        "bypass": "See recaptcha_v3.py -- anchor/reload HTTP trick",
    },
}


if __name__ == "__main__":
    import json
    print("=== RocketReach Internal API Endpoints ===\n")
    for name, info in ENDPOINTS.items():
        print(f"  {info.get('method', '?'):6s} {info['url']}")
        if 'fields' in info:
            print(f"         Fields: {', '.join(info['fields'].keys())}")
        print()
    print("=== Signup Form Structure ===\n")
    print(json.dumps(SIGNUP_FORM, indent=2))
