# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Alertmanager Remote Configurer library.

This library provides possibility of configuring the Alertmanager through another Juju charm.
It has been created with the `alertmanager-k8s` and the `alertmanager-k8s-configurer` charms in
mind, but can be used by any charms which require functionalities implemented by this library.

Charms that need to push Alertmanager configuration to a charm exposing relation using
the `alertmanager_remote_configurer` interface, should use
the `AlertmanagerRemoteConfigurerConsumer`.
Charms that need to can utilize the Alertmanager configuration provided from the external source
through a relation using the `alertmanager_remote_configurer` interface, should use
the `AlertmanagerRemoteConfigurerProvider`.

For custom consumer implementations, two additional methods are available - `load_config_file` and
`load_templates_file`. They can be used to prepare the relevant data to be pushed to the relation
data bag.
"""

import json
import logging
import os
from typing import Union

import requests
import yaml
from jsonschema import exceptions, validate  # type: ignore[import]
from ops.charm import CharmBase, RelationChangedEvent, RelationJoinedEvent
from ops.framework import Object
from ops.model import BlockedStatus, Relation

# The unique Charmhub library identifier, never change it
LIBID = "something dummy for now"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

logger = logging.getLogger(__name__)

ALERTMANAGER_CONFIG_JSON_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Alertmanager",
    "description": "Alertmanager configuration file schema.",
    "type": "object",
    "properties": {
        "global": {
            "description": "The global configuration specifies parameters that are valid in all other configuration contexts. They also serve as defaults for other configuration sections.",  # noqa: E501
            "type": "object",
            "properties": {
                "http_config": {
                    "description": "The default HTTP client configuration.",
                    "$ref": "#/definitions/http_config",
                },
                "resolve_timeout": {
                    "description": "ResolveTimeout is the default value used by alertmanager if the alert does not include EndsAt, after this time passes it can declare the alert as resolved if it has not been updated. This has no impact on alerts from Prometheus, as they always include EndsAt.",  # noqa: E501
                    "$ref": "#/definitions/duration",
                    "default": "5m",
                },
                "smtp_from": {
                    "description": "The default SMTP From header field.",
                    "type": "string",
                    "format": "email",
                },
                "smtp_smarthost": {
                    "description": "The default SMTP smarthost used for sending emails, including port number. Port number usually is 25, or 587 for SMTP over TLS (sometimes referred to as STARTTLS). Example: smtp.example.org:587",  # noqa: E501
                    "type": "string",
                },
                "smtp_hello": {
                    "description": "The default hostname to identify to the SMTP server.",
                    "type": "string",
                    "format": "hostname",
                    "default": "localhost",
                },
                "smtp_auth_username": {
                    "description": "SMTP Auth using CRAM-MD5, LOGIN and PLAIN. If empty, Alertmanager doesn't authenticate to the SMTP server.",  # noqa: E501
                    "type": "string",
                },
                "smtp_auth_password": {
                    "description": "SMTP Auth using LOGIN and PLAIN.",
                    "type": "string",
                },
                "smtp_auth_identity": {
                    "description": "SMTP Auth using PLAIN.",
                    "type": "string",
                },
                "smtp_auth_secret": {
                    "description": "SMTP Auth using CRAM-MD5.",
                    "type": "string",
                },
                "smtp_require_tls": {
                    "description": "The default SMTP TLS requirement. Note that Go does not support unencrypted connections to remote SMTP endpoints.",  # noqa: E501
                    "type": "boolean",
                    "default": True,
                },
                "slack_api_url": {
                    "type": "string",
                    "format": "uri-reference",
                },
                "slack_api_url_file": {
                    "$ref": "#/definitions/filepath",
                },
                "victorops_api_key": {
                    "type": "string",
                },
                "victorops_api_url": {
                    "type": "string",
                    "format": "uri-reference",
                    "default": "https://alert.victorops.com/integrations/generic/20131114/alert/",
                },
                "pagerduty_url": {
                    "type": "string",
                    "format": "uri-reference",
                    "default": "https://events.pagerduty.com/v2/enqueue",
                },
                "opsgenie_api_key": {
                    "type": "string",
                },
                "opsgenie_api_key_file": {
                    "$ref": "#/definitions/filepath",
                },
                "opsgenie_api_url": {
                    "type": "string",
                    "format": "uri-reference",
                    "default": "https://api.opsgenie.com/",
                },
                "wechat_api_url": {
                    "type": "string",
                    "format": "uri-reference",
                    "default": "https://qyapi.weixin.qq.com/cgi-bin/",
                },
                "wechat_api_secret": {
                    "type": "string",
                },
                "wechat_api_corp_id": {
                    "type": "string",
                },
                "telegram_api_url": {
                    "type": "string",
                    "format": "uri-reference",
                    "default": "https://api.telegram.org",
                },
            },
            "additionalProperties": False,
        },
        "route": {
            "description": "The root node of the routing tree.",
            "type": "object",
            "properties": {
                "receiver": {
                    "type": "string",
                },
                "group_by": {
                    "description": "The labels by which incoming alerts are grouped together. For example, multiple alerts coming in for cluster=A and alertname=LatencyHigh would be batched into a single group. To aggregate by all possible labels use the special value '...' as the sole label name, for example: group_by: ['...'] This effectively disables aggregation entirely, passing through all alerts as-is. This is unlikely to be what you want, unless you have a very low alert volume or your upstream notification system performs its own grouping.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/label_name"},
                    "additionalItems": False,
                },
                "continue": {
                    "description": "Whether an alert should continue matching subsequent sibling nodes.",  # noqa: E501
                    "type": "boolean",
                    "default": False,
                },
                "group_wait": {
                    "description": "How long to initially wait to send a notification for a group of alerts. Allows to wait for an inhibiting alert to arrive or collect more initial alerts for the same group. (Usually ~0s to few minutes.)",  # noqa: E501
                    "$ref": "#/definitions/duration",
                    "default": "30s",
                },
                "group_interval": {
                    "description": "How long to wait before sending a notification about new alerts that are added to a group of alerts for which an initial notification has already been sent. (Usually ~5m or more.)",  # noqa: E501
                    "$ref": "#/definitions/duration",
                    "default": "5m",
                },
                "repeat_interval": {
                    "description": "How long to wait before sending a notification again if it has already been sent successfully for an alert. (Usually ~3h or more).",  # noqa: E501
                    "$ref": "#/definitions/duration",
                    "default": "4h",
                },
                "routes": {
                    "description": "Zero or more child routes.",
                    "type": "array",
                    "items": {"$ref": "#/definitions/route"},
                    "additionalItems": False,
                },
            },
            "additionalProperties": False,
            "anyOf": [
                {
                    "properties": {
                        "match": {
                            "description": "A set of equality matchers an alert has to fulfill to match the node.",  # noqa: E501
                            "type": "array",
                            "items": {"$ref": "#/definitions/label_name_string_key_value_map"},
                        }
                    }
                },
                {
                    "properties": {
                        "match_re": {
                            "description": "A set of regex-matchers an alert has to fulfill to match the node.",  # noqa: E501
                            "type": "array",
                            "items": {"$ref": "#/definitions/label_regex_key_value_map"},
                        }
                    }
                },
                {
                    "properties": {
                        "matchers": {
                            "description": "A list of matchers that an alert has to fulfill to match the node.",  # noqa: E501
                            "type": "array",
                            "items": {"$ref": "#/definitions/matcher"},
                        }
                    }
                },
            ],
        },
        "receivers": {
            "description": "A list of notification receivers.",
            "type": "array",
            "items": {"$ref": "#/definitions/receiver"},
            "additionalItems": False,
        },
        "inhibit_rules": {
            "description": "A list of inhibition rules.",
            "type": "array",
            "items": {"$ref": "#/definitions/inhibit_rule"},
            "additionalItems": False,
        },
        "time_intervals": {
            "description": "A list of time intervals for muting/activating routes.",
            "type": "array",
            "items": {"$ref": "#/definitions/time_interval"},
            "additionalItems": False,
        },
        "templates": {
            "description": "Files from which custom notification template definitions are read. The last component may use a wildcard matcher, e.g. 'templates/*.tmpl'.",  # noqa: E501
            "type": "array",
            "items": {"$ref": "#/definitions/filepath"},
            "additionalItems": False,
        },
    },
    "additionalProperties": False,
    "definitions": {
        "action_config": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                },
                "dismiss_text": {
                    "type": "string",
                    "default": "",
                },
                "ok_text": {
                    "type": "string",
                    "default": "",
                },
                "title": {
                    "type": "string",
                    "default": "",
                },
            },
            "additionalProperties": False,
            "required": ["text"],
        },
        "authorization": {
            "description": "Optional the `Authorization` header configuration.",
            "type": "object",
            "properties": {
                "type": {
                    "description": "Sets the authentication type.",
                    "type": "string",
                    "default": "Bearer",
                },
                "credentials": {
                    "description": "Sets the credentials. It is mutually exclusive with `credentials_file`.",  # noqa: E501
                    "type": "string",
                },
                "credentials_file": {
                    "description": "Sets the credentials with the credentials read from the configured file. It is mutually exclusive with `credentials`.",  # noqa: E501
                    "$ref": "#/definitions/filepath",
                },
            },
            "oneOf": [{"required": ["credentials"]}, {"required": ["credentials_file"]}],
            "additionalProperties": False,
            "required": ["type"],
        },
        "basic_auth": {
            "description": "Sets the `Authorization` header on every remote write request with the configured username and password. password and password_file are mutually exclusive.",  # noqa: E501
            "type": "string",
            "properties": {
                "username": {
                    "type": "string",
                },
                "password": {
                    "type": "string",
                },
                "password_file": {
                    "$ref": "#/definitions/filepath",
                },
            },
            "oneOf": [{"required": ["password"]}, {"required": ["password_file"]}],
            "additionalProperties": False,
            "required": ["username"],
        },
        "days_of_month": {
            "description": "A numerical value of day in the month. Negative values are also accepted which begin at the end of the month, e.g. -1 during January would represent January 31. For example: '1:5' or '-3:-1'. Extending past the start or end of the month will cause it to be clamped. E.g. specifying '1:31' during February will clamp the actual end date to 28 or 29 depending on leap years. Ranges are inclusive on both ends.",  # noqa: E501
            "type": "string",
            "pattern": "^-?(3[01]?|[12]\\d?|[4-9])(:-?(3[01]?|[12]\\d?|[4-9]))?$",
        },
        "duration": {
            "type": "string",
            "pattern": "^(((\\d+)y)?((\\d+)w)?((\\d+)d)?((\\d+)h)?((\\d+)m)?((\\d+)s)?((\\d+)ms)?|0)$",  # noqa: E501
        },
        "email_config": {
            "type": "object",
            "properties": {
                "send_resolved": {
                    "description": "Whether to notify about resolved alerts.",
                    "type": "boolean",
                    "default": False,
                },
                "to": {
                    "description": "The email address to send notifications to.",
                    "type": "string",
                    "format": "email",
                },
                "from": {
                    "description": "The sender's address. Defaults to global.smtp_from.",
                    "type": "string",
                    "format": "email",
                },
                "smarthost": {
                    "description": "The SMTP host through which emails are sent. Defaults to global.smtp_smarthost.",  # noqa: E501
                    "type": "string",
                },
                "hello": {
                    "description": "The hostname to identify to the SMTP server. Defaults to global.smtp_hello.",  # noqa: E501
                    "type": "string",
                },
                "auth_username": {
                    "description": "SMTP authentication information. Defaults to global.smtp_auth_username.",  # noqa: E501
                    "type": "string",
                },
                "auth_password": {
                    "description": "SMTP authentication information. Defaults to global.smtp_auth_password.",  # noqa: E501
                    "type": "string",
                },
                "auth_secret": {
                    "description": "SMTP authentication information. Defaults to global.smtp_auth_secret.",  # noqa: E501
                    "type": "string",
                },
                "auth_identity": {
                    "description": "SMTP authentication information. Defaults to global.smtp_auth_identity.",  # noqa: E501
                    "type": "string",
                },
                "require_tls": {
                    "description": "The SMTP TLS requirement. Note that Go does not support unencrypted connections to remote SMTP endpoints.",  # noqa: E501
                    "type": "boolean",
                },
                "tls_config": {
                    "description": "TLS configuration.",
                    "#ref": "#/definitions/tls_config",
                },
                "html": {
                    "description": "The HTML body of the email notification.",
                    "type": "string",
                    "default": '{{ template "email.default.html" . }}',
                },
                "text": {
                    "description": "The text body of the email notification.",
                    "type": "string",
                },
                "headers": {
                    "description": "Further headers email header key/value pairs. Overrides any headers previously set by the notification implementation.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/string_string_key_value_map"},
                },
            },
            "additionalItems": False,
            "required": ["to"],
        },
        "field_config": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                },
                "value": {
                    "type": "string",
                },
                "short": {
                    "description": "Defaults to slack_config.short_fields.",
                    "type": "boolean",
                },
            },
            "additionalProperties": False,
            "required": ["title", "value"],
        },
        "filepath": {
            "type": "string",
            "format": "uri-reference",
        },
        "http_config": {
            "type": "object",
            "properties": {
                "proxy_url": {
                    "description": "Optional proxy URL.",
                    "type": "string",
                    "format": "uri-reference",
                },
                "follow_redirects": {
                    "description": "Configure whether HTTP requests follow HTTP 3xx redirects.",
                    "type": "boolean",
                    "default": True,
                },
                "tls_config": {
                    "description": "Configures the TLS settings.",
                    "#ref": "#/definitions/tls_config",
                },
            },
            "anyOf": [
                {
                    "properties": {
                        "basic_auth": {
                            "description": "Sets the `Authorization` header with the configured username and password.",  # noqa: E501
                            "#ref": "#/definitions/basic_auth",
                        }
                    }
                },
                {
                    "properties": {
                        "authorization": {
                            "description": "Optional the `Authorization` header configuration.",
                            "#ref": "#/definitions/authorization",
                        }
                    }
                },
                {
                    "properties": {
                        "oauth2": {
                            "description": "Optional OAuth 2.0 configuration. Cannot be used at the same time as basic_auth or authorization.",  # noqa: E501
                            "#ref": "#/definitions/oauth2",
                        }
                    }
                },
            ],
            "additionalProperties": False,
            "required": ["tls_config"],
        },
        "image_config": {
            "type": "object",
            "properties": {
                "href": {
                    "description": "Optional URL; makes the image a clickable link.",
                    "type": "string",
                    "format": "uri-reference",
                },
                "source": {
                    "description": "The source (URL) of the image being attached to the incident. This image must be served via HTTPS.",  # noqa: E501
                    "type": "string",
                    "format": "uri-reference",
                },
                "alt": {
                    "description": "Optional alternative text for the image.",
                    "type": "string",
                },
            },
            "additionalProperties": False,
            "required": ["href", "source", "alt"],
        },
        "inhibit_rule": {
            "description": "An inhibition rule mutes an alert (target) matching a set of matchers when an alert (source) exists that matches another set of matchers. Both target and source alerts must have the same label values for the label names in the equal list.",  # noqa: E501
            "type": "object",
            "anyOf": [
                {
                    "anyOf": [
                        {"required": ["source_match"]},
                        {"required": ["source_match_re"]},
                        {"required": ["source_matchers"]},
                    ]
                },
                {
                    "anyOf": [
                        {"required": ["target_match"]},
                        {"required": ["target_match_re"]},
                        {"required": ["target_matchers"]},
                    ]
                },
            ],
            "properties": {
                "source_match": {
                    "description": "DEPRECATED: Use source_matchers. Matchers for which one or more alerts have to exist for the inhibition to take effect.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/label_name_string_key_value_map"},
                    "additionalItems": False,
                },
                "source_match_re": {
                    "description": "DEPRECATED: Use source_matchers. Matchers for which one or more alerts have to exist for the inhibition to take effect.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/label_regex_key_value_map"},
                    "additionalItems": False,
                },
                "source_matchers": {
                    "description": "A list of matchers for which one or more alerts have to exist for the inhibition to take effect.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/matcher"},
                    "additionalItems": False,
                },
                "target_match": {
                    "description": "DEPRECATED: Use target_matchers. Matchers that have to be fulfilled in the alerts to be muted.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/label_name_string_key_value_map"},
                    "additionalItems": False,
                },
                "target_match_re": {
                    "description": "DEPRECATED: Use target_matchers. Matchers that have to be fulfilled in the alerts to be muted.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/label_regex_key_value_map"},
                    "additionalItems": False,
                },
                "target_matchers": {
                    "description": "A list of matchers that have to be fulfilled by the target alerts to be muted.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/matcher"},
                    "additionalItems": False,
                },
                "equal": {
                    "description": "Labels that must have an equal value in the source and target alert for the inhibition to take effect.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/label_name"},
                    "additionalItems": False,
                },
            },
            "additionalProperties": False,
        },
        "label_name": {
            "type": "string",
            "pattern": "^[a-zA-Z_]\\w*$",
        },
        "label_name_string_key_value_map": {
            "type": "object",
            "patternProperties": {"^[a-zA-Z_]\\w*$": {"type": "string"}},
            "additionalProperties": False,
        },
        "label_regex_key_value_map": {
            "type": "object",
            "patternProperties": {"^[a-zA-Z_]\\w*$": {"format": "regex"}},
            "additionalProperties": False,
        },
        "link_config": {
            "type": "object",
            "properties": {
                "href": {
                    "description": "URL of the link to be attached.",
                    "type": "string",
                    "format": "uri-reference",
                },
                "text": {
                    "description": "Plain text that describes the purpose of the link, and can be used as the link's text.",  # noqa: E501
                    "type": "string",
                },
            },
            "additionalProperties": False,
            "required": ["href", "text"],
        },
        "matcher": {
            "type": "string",
            "pattern": '^{?("?\\w+"?\\s?(?:=|!=|=~|!~)\\\\?"?[\\w+_\\-,|]+\\\\?"?)(,\\s?($1))?}?$',
        },
        "months": {
            "description": "Months identified by a case-insensitive name (e.g. 'January') or by number, where January = 1. Ranges are also accepted and are nclusive on both ends. Example: ['1:3', 'may:august', 'december'].",  # noqa: E501
            "type": "string",
            "pattern": "^([Jj]anuary|[Ff]ebruary|[Mm]arch|[Aa]pril|[Mm]ay|[Jj]une|[Jj]uly|[Aa]ugust|[Ss]eptember|[Oo]ctober|[Nn]ovember|[Dd]ecember|[1-9]|1[0-2])(:($1))?$",  # noqa: E501
        },
        "oauth2": {
            "description": "Optional OAuth 2.0 configuration. Cannot be used at the same time as basic_auth or authorization.",  # noqa: E501
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "string",
                },
                "client_secret": {
                    "description": "It is mutually exclusive with `client_secret_file`.",
                    "type": "string",
                },
                "client_secret_file": {
                    "description": "Read the client secret from a file. It is mutually exclusive with `client_secret`.",  # noqa: E501
                    "$ref": "#/definitions/filepath",
                },
                "scopes": {
                    "description": "Scopes for the token request.",
                    "type": "array",
                    "items": {"type": "string"},
                    "additionalItems": False,
                },
                "token_url": {
                    "description": "The URL to fetch the token from.",
                    "type": "string",
                    "format": "uri-reference",
                },
                "endpoint_params": {
                    "description": "Optional parameters to append to the token URL.",
                    "$ref": "#/definitions/string_string_key_value_map",
                },
            },
            "additionalProperties": False,
            "required": ["client_id", "scopes", "token_url", "endpoint_params"],
        },
        "opsgenie_config": {
            "description": "OpsGenie notifications are sent via the OpsGenie API.",
            "type": "object",
            "properties": {
                "send_resolved": {
                    "description": "Whether to notify about resolved alerts.",
                    "type": "boolean",
                    "default": True,
                },
                "api_url": {
                    "description": "The host to send OpsGenie API requests to. Defaults to global.opsgenie_api_url.",  # noqa: E501
                    "type": "string",
                    "format": "uri-reference",
                },
                "message": {
                    "description": "Alert text limited to 130 characters.",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "maxLength": 130,
                    "default": '{{ template "opsgenie.default.message" . }}',
                },
                "description": {
                    "description": "A description of the alert.",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "opsgenie.default.description" . }}',
                },
                "source": {
                    "description": "A backlink to the sender of the notification.",
                    "$ref": "#/definitions/url_or_template_ref_value",
                    "default": '{{ template "opsgenie.default.source" . }}',
                },
                "details": {
                    "description": "A set of arbitrary key/value pairs that provide further detail about the alert. All common labels are included as details by default.",  # noqa: E501
                    "$ref": "#/definitions/string_string_key_value_map",
                },
                "responders": {
                    "description": "List of responders responsible for notifications.",
                    "type": "array",
                    "items": {"$ref": "#/definitions/responder"},
                    "additionalItems": False,
                },
                "tags": {
                    "description": "Comma separated list of tags attached to the notifications.",  # noqa: E501
                    "type": "string",
                    "pattern": "^(\\w+)(,\\s*\\w+)*$",
                },
                "note": {
                    "description": "Additional alert note.",
                    "type": "string",
                },
                "priority": {
                    "description": "Priority level of alert. Possible values are P1, P2, P3, P4, and P5.",  # noqa: E501
                    "type": "string",
                    "enum": ["P1", "P2", "P3", "P4", "P5"],
                },
                "update_alerts": {
                    "description": "Whether to update message and description of the alert in OpsGenie if it already exists. By default, the alert is never updated in OpsGenie, the new message only appears in activity log.",  # noqa: E501
                    "type": "boolean",
                    "default": False,
                },
                "entity": {
                    "description": "Optional field that can be used to specify which domain alert is related to.",  # noqa: E501
                    "type": "string",
                },
                "actions": {
                    "description": "Comma separated list of actions that will be available for the alert.",  # noqa: E501
                    "type": "string",
                    "pattern": "^(\\w+)(,\\s*\\w+)*$",
                },
                "http_config": {
                    "description": "The HTTP client's configuration. Defaults to global.http_config.",  # noqa: E501
                    "$ref": "#/definitions/http_config",
                },
            },
            "anyOf": [
                {
                    "properties": {
                        "api_key": {
                            "description": "The API key to use when talking to the OpsGenie API. Defaults to global.opsgenie_api_key.",  # noqa: E501
                            "type": "string",
                        },
                        "api_key_file": {
                            "description": "The filepath to API key to use when talking to the OpsGenie API. Conflicts with api_key. Defaults to global.opsgenie_api_key_file",  # noqa: E501
                            "$ref": "#/definitions/filepath",
                        },
                    }
                }
            ],
            "additionalProperties": False,
            "required": ["responders"],
        },
        "pagerduty_config": {
            "description": "PagerDuty notifications are sent via the PagerDuty API.",
            "type": "object",
            "properties": {
                "send_resolved": {
                    "description": "Whether to notify about resolved alerts.",
                    "type": "boolean",
                    "default": True,
                },
                "routing_key": {
                    "description": "The PagerDuty integration key (when using PagerDuty integration type `Events API v2`). Mutually exclusive with service_key.",  # noqa: E501
                    "type": "string",
                },
                "service_key": {
                    "description": "The PagerDuty integration key (when using PagerDuty integration type `Prometheus`). utually exclusive with routing_key.",  # noqa: E501
                    "type": "string",
                },
                "url": {
                    "description": "The URL to send API requests to. Defaults to global.pagerduty_url.",  # noqa: E501
                    "type": "string",
                    "format": "uri-reference",
                },
                "client": {
                    "description": "The client identification of the Alertmanager.",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "pagerduty.default.client" . }}',
                },
                "client_url": {
                    "description": "A backlink to the sender of the notification.",
                    "$ref": "#/definitions/url_or_template_ref_value",
                    "default": '{{ template "pagerduty.default.clientURL" . }}',
                },
                "description": {
                    "description": "A description of the incident.",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "pagerduty.default.description" .}}',
                },
                "severity": {
                    "description": "Severity of the incident.",
                    "type": "string",
                    "enum": ["info", "warning", "error", "critical"],
                    "default": "error",
                },
                "details": {
                    "description": "A set of arbitrary key/value pairs that provide further details about the incident.",  # noqa: E501
                    "$ref": "#/definitions/string_template_name_key_value_map",
                    "default": {
                        "firing": '{{ template "pagerduty.default.instances" .Alerts.Firing }}',
                        "resolved": '{{ template "pagerduty.default.instances" .Alerts.Resolved }}',  # noqa: E501
                        "num_firing": "{{ .Alerts.Firing | len }}",
                        "num_resolved": "{{ .Alerts.Resolved | len }}",
                    },
                },
                "images": {
                    "description": "Images to attach to the incident.",
                    "type": "array",
                    "items": {"$ref": "#/definitions/image_config"},
                    "additionalItems": False,
                },
                "links": {
                    "description": "Links to attach to the incident.",
                    "type": "array",
                    "items": {"$ref": "#/definitions/link_config"},
                    "additionalItems": False,
                },
                "component": {
                    "description": "The part or component of the affected system that is broken.",
                    "type": "string",
                },
                "group": {
                    "description": "A cluster or grouping of sources.",
                    "type": "string",
                },
                "class": {
                    "description": "The class/type of the event.",
                    "type": "string",
                },
                "http_config": {
                    "description": "The HTTP client's configuration. Defaults to global.http_config",  # noqa: E501
                    "$ref": "#/definitions/http_config",
                },
            },
            "oneOf": [{"required": ["routing_key"]}, {"required": ["service_key"]}],
            "additionalProperties": False,
        },
        "pushover_config": {
            "description": "Pushover notifications are sent via the Pushover API.",
            "type": "object",
            "properties": {
                "send_resolved": {
                    "description": "Whether to notify about resolved alerts.",
                    "type": "boolean",
                    "default": True,
                },
                "user_key": {
                    "description": "The recipient user's user key.",
                    "type": "string",
                },
                "token": {
                    "description": "Your registered application's API token, see https://pushover.net/apps. You can also register a token by cloning this Prometheus app: https://pushover.net/apps/clone/prometheus.",  # noqa: E501
                    "type": "string",
                },
                "title": {
                    "description": "Notification title.",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "pushover.default.title" . }}',
                },
                "message": {
                    "description": "Notification message.",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "pushover.default.message" . }}',
                },
                "url": {
                    "description": "A supplementary URL shown alongside the message.",
                    "$ref": "#/definitions/url_or_template_ref_value",
                    "default": '{{ template "pushover.default.url" . }}',
                },
                "priority": {
                    "description": "Priority, see https://pushover.net/api#priority",
                    "type": "string",
                    "enum": ["-2", "-1", "0", "1", "2"],
                    "default": '{{ if eq .Status "firing" }}2{{ else }}0{{ end }}',
                },
                "retry": {
                    "description": "How often the Pushover servers will send the same notification to the user. Must be at least 30 seconds.",  # noqa: E501
                    "$ref": "#/definitions/duration",
                    "default": "1m",
                },
                "expire": {
                    "description": "How long your notification will continue to be retried for, unless the user acknowledges the notification.",  # noqa: E501
                    "$ref": "#/definitions/duration",
                    "default": "1h",
                },
                "http_config": {
                    "description": "The HTTP client's configuration. Defaults to global.http_config.",  # noqa: E501
                    "$ref": "#/definitions/http_config",
                },
            },
            "additionalProperties": False,
            "required": ["user_key", "token"],
        },
        "receiver": {
            "description": "Receiver is a named configuration of one or more notification integrations.",  # noqa: E501
            "type": "object",
            "properties": {
                "name": {
                    "description": "The unique name of the receiver.",
                    "type": "string",
                },
                "email_configs": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/email_config"},
                    "additionalItems": False,
                },
                "opsgenie_configs": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/opsgenie_config"},
                    "additionalItems": False,
                },
                "pagerduty_configs": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/pagerduty_config"},
                    "additionalItems": False,
                },
                "pushover_configs": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/pushover_config"},
                    "additionalItems": False,
                },
                "slack_configs": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/slack_config"},
                    "additionalItems": False,
                },
                "sns_configs": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/sns_config"},
                    "additionalItems": False,
                },
                "victorops_configs": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/victorops_config"},
                    "additionalItems": False,
                },
                "webhook_configs": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/webhook_config"},
                    "additionalItems": False,
                },
                "wechat_configs": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/wechat_config"},
                    "additionalItems": False,
                },
                "telegram_configs": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/telegram_configs"},
                    "additionalItems": False,
                },
            },
            "additionalProperties": False,
            "required": ["name"],
        },
        "responder": {
            "type": "object",
            "oneOf": [
                {
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "username": {"type": "string"},
                    }
                }
            ],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["team", "teams", "user", "escalation", "schedule"],
                }
            },
            "additionalProperties": False,
            "required": ["type"],
        },
        "route": {
            "type": "object",
            "properties": {
                "receiver": {
                    "type": "string",
                },
                "group_by": {
                    "description": "The labels by which incoming alerts are grouped together. For example, multiple alerts coming in for cluster=A and alertname=LatencyHigh would be batched into a single group. To aggregate by all possible labels use the special value '...' as the sole label name, for example: group_by: ['...'] This effectively disables aggregation entirely, passing through all alerts as-is. This is unlikely to be what you want, unless you have a very low alert volume or your upstream notification system performs its own grouping.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/label_name"},
                    "additionalItems": False,
                },
                "continue": {
                    "description": "Whether an alert should continue matching subsequent sibling nodes.",  # noqa: E501
                    "type": "boolean",
                    "default": False,
                },
                "match": {
                    "description": "A set of equality matchers an alert has to fulfill to match the node.",  # noqa: E501
                    "$ref": "#/definitions/label_name_string_key_value_map",
                },
                "match_re": {
                    "description": "A set of regex-matchers an alert has to fulfill to match the node.",  # noqa: E501
                    "$ref": "#/definitions/label_name_string_key_value_map",
                },
                "matchers": {
                    "description": "A list of matchers that an alert has to fulfill to match the node.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/matcher"},
                    "additionalItems": False,
                },
                "group_wait": {
                    "description": "How long to initially wait to send a notification for a group of alerts. Allows to wait for an inhibiting alert to arrive or collect more initial alerts for the same group. (Usually ~0s to few minutes.)",  # noqa: E501
                    "$ref": "#/definitions/duration",
                    "default": "30s",
                },
                "group_interval": {
                    "description": "How long to wait before sending a notification about new alerts that are added to a group of alerts for which an initial notification has already been sent. (Usually ~5m or more.)",  # noqa: E501
                    "$ref": "#/definitions/duration",
                    "default": "5m",
                },
                "repeat_interval": {
                    "description": "How long to wait before sending a notification again if it has already been sent successfully for an alert. (Usually ~3h or more).",  # noqa: E501
                    "$ref": "#/definitions/duration",
                    "default": "4h",
                },
                "mute_time_intervals": {
                    "description": "Times when the route should be muted. These must match the name of a mute time interval defined in the mute_time_intervals section. Additionally, the root node cannot have any mute times. When a route is muted it will not send any notifications, but otherwise acts normally (including ending the route-matching process if the `continue` option is not set.)",  # noqa: E501
                    "type": "array",
                    "items": {"type": "string"},
                    "additionalItems": False,
                },
                "active_time_intervals": {
                    "description": "Times when the route should be active. These must match the name of a time interval defined in the time_intervals section. An empty value means that the route is always active. Additionally, the root node cannot have any active times. The route will send notifications only when active, but otherwise acts normally (including ending the route-matching process if the `continue` option is not set).",  # noqa: E501
                    "type": "array",
                    "items": {"type": "string"},
                    "additionalItems": False,
                },
                "routes": {
                    "description": "Zero or more child routes.",
                    "type": "array",
                    "items": {"$ref": "#/definitions/route"},
                    "additionalItems": False,
                },
            },
            "anyOf": [
                {"required": ["match"]},
                {"required": ["match_re"]},
                {"required": ["matchers"]},
            ],
            "additionalProperties": False,
        },
        "sigv4_config": {
            "type": "object",
            "properties": {
                "region": {
                    "description": "The AWS region. If blank, the region from the default credentials chain is used.",  # noqa: E501
                    "type": "string",
                },
                "access_key": {
                    "description": "The AWS API key. Both access_key and secret_key must be supplied or both must be blank. If blank the environment variables `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are used.",  # noqa: E501
                    "type": "string",
                },
                "secret_key": {
                    "description": "The AWS API key. Both access_key and secret_key must be supplied or both must be blank. If blank the environment variables `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are used.",  # noqa: E501
                    "type": "string",
                },
                "profile": {
                    "description": "Named AWS profile used to authenticate.",
                    "type": "string",
                },
                "role_arn": {
                    "description": "AWS Role ARN, an alternative to using AWS API keys.",
                    "type": "string",
                },
            },
            "dependencies": {"access_key": ["secret_key"], "secret_key": ["access_key"]},
            "additionalProperties": False,
        },
        "slack_config": {
            "description": "Slack notifications are sent via Slack webhooks. The notification contains an attachment.",  # noqa: E501
            "type": "object",
            "properties": {
                "send_resolved": {
                    "description": "Whether to notify about resolved alerts.",
                    "type": "boolean",
                    "default": True,
                },
                "channel": {
                    "description": "The channel or user to send notifications to.",
                    "type": "string",
                },
                "icon_emoji": {
                    "description": "API request data as defined by the Slack webhook API.",
                    "type": "string",
                },
                "icon_url": {
                    "description": "API request data as defined by the Slack webhook API.",
                    "type": "string",
                    "format": "uri-reference",
                },
                "link_names": {
                    "description": "API request data as defined by the Slack webhook API.",
                    "type": "boolean",
                    "default": False,
                },
                "username": {
                    "description": "API request data as defined by the Slack webhook API.",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "slack.default.username" . }}',
                },
                "actions": {
                    "description": "Define the attachment",
                    "type": "array",
                    "items": {"$ref": "#/definitions/action_config"},
                    "additionalItems": False,
                },
                "callback_id": {
                    "description": "Define the attachment",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "slack.default.callbackid" . }}',
                },
                "color": {
                    "description": "Define the attachment",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ if eq .Status "firing" }}danger{{ else }}good{{ end }}',
                },
                "fallback": {
                    "description": "Define the attachment",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "slack.default.fallback" . }}',
                },
                "fields": {
                    "description": "Define the attachment",
                    "type": "array",
                    "items": {"$ref": "#/definitions/field_config"},
                    "additionalItems": False,
                },
                "footer": {
                    "description": "Define the attachment",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "slack.default.footer" . }}',
                },
                "mrkdwn_in": {
                    "description": "Define the attachment",
                    "type": "array",
                    "items": {"type": "string"},
                    "additionalItems": False,
                    "default": ["fallback", "pretext", "text"],
                },
                "pretext": {
                    "description": "Define the attachment",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "slack.default.pretext" . }}',
                },
                "short_fields": {
                    "description": "Define the attachment",
                    "type": "boolean",
                    "default": False,
                },
                "text": {
                    "description": "Define the attachment",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "slack.default.text" . }}',
                },
                "title": {
                    "description": "Define the attachment",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "slack.default.title" . }}',
                },
                "title_link": {
                    "description": "Define the attachment",
                    "$ref": "#/definitions/url_or_template_ref_value",
                    "format": "uri-reference",
                    "default": '{{ template "slack.default.titlelink" . }}',
                },
                "image_url": {
                    "description": "Define the attachment",
                    "type": "string",
                    "format": "uri-reference",
                },
                "thumb_url": {
                    "description": "Define the attachment",
                    "type": "string",
                    "format": "uri-reference",
                },
                "http_config": {
                    "description": "The HTTP client's configuration. Defaults to global.http_config.",  # noqa: E501
                    "$ref": "#/definitions/http_config",
                },
            },
            "anyOf": [
                {
                    "properties": {
                        "api_url": {
                            "description": "Mutually exclusive with api_url_file. Defaults to global.slack_api_url.",  # noqa: E501
                            "type": "string",
                            "format": "uri-reference",
                        },
                        "api_url_file": {
                            "description": "Mutually exclusive with api_url. Defaults to global.slack_api_url_file.",  # noqa: E501
                            "$ref": "#/definitions/filepath",
                        },
                    }
                }
            ],
            "additionalProperties": False,
            "required": ["channel", "actions", "fields"],
        },
        "sns_config": {
            "type": "object",
            "properties": {
                "send_resolved": {
                    "description": "Whether to notify about resolved alerts.",
                    "type": "boolean",
                    "default": True,
                },
                "api_url": {
                    "description": "The SNS API URL i.e. https://sns.us-east-2.amazonaws.com. If not specified, the SNS API URL from the SNS SDK will be used.",  # noqa: E501
                    "type": "string",
                    "format": "uri-reference",
                },
                "sigv4": {
                    "description": "Configures AWS's Signature Verification 4 signing process to sign requests.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/sigv4_config"},
                    "additionalItems": False,
                },
                "topic_arn": {
                    "description": "SNS topic ARN, i.e. arn:aws:sns:us-east-2:698519295917:My-Topic. If you don't specify this value, you must specify a value for the phone_number or target_arn. If you are using a FIFO SNS topic you should set a message group interval longer than 5 minutes to prevent messages with the same group key being deduplicated by the SNS default deduplication window.",  # noqa: E501
                    "type": "string",
                },
                "subject": {
                    "description": "Subject line when the message is delivered to email endpoints.",  # noqa: E501
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "sns.default.subject" . }}',
                },
                "phone_number": {
                    "description": "Phone number if message is delivered via SMS in E.164 format. If you don't specify this value, you must specify a value for the topic_arn or target_arn.",  # noqa: E501
                    "type": "string",
                },
                "target_arn": {
                    "description": "The mobile platform endpoint ARN if message is delivered via mobile notifications. If you don't specify this value, you must specify a value for the topic_arn or phone_number.",  # noqa: E501
                    "type": "string",
                },
                "message": {
                    "description": "The message content of the SNS notification.",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "sns.default.message" . }}',
                },
                "attributes": {
                    "description": "SNS message attributes.",
                    "type": "array",
                    "items": {"$ref": "#/definitions/string_string_key_value_map"},
                    "additionalItems": False,
                },
                "http_config": {
                    "description": "The HTTP client's configuration. Defaults to global.http_config.",  # noqa: E501
                    "$ref": "#/definitions/http_config",
                },
            },
            "additionalProperties": False,
            "required": ["sigv4", "attributes"],
        },
        "string_or_template_ref_value": {
            "oneOf": [{"type": "string"}, {"$ref": "#/definitions/template_reference"}]
        },
        "string_string_key_value_map": {
            "type": "object",
            "patternProperties": {".+": {"type": "string"}},
        },
        "string_template_name_key_value_map": {
            "type": "object",
            "patternProperties": {".+": {"$ref": "#/definitions/template_reference"}},
        },
        "telegram_configs": {
            "type": "object",
            "properties": {
                "send_resolved": {
                    "description": "Whether to notify about resolved alerts.",
                    "type": "boolean",
                    "default": True,
                },
                "api_url": {
                    "description": "The Telegram API URL i.e. https://api.telegram.org. If not specified, default API URL will be used. Defaults to global.telegram_api_url.",  # noqa: E501
                    "type": "string",
                    "format": "uri-reference",
                },
                "bot_token": {
                    "description": "Telegram bot token.",
                    "type": "string",
                },
                "chat_id": {
                    "description": "ID of the chat where to send the messages.",
                    "type": "number",
                },
                "message": {
                    "description": "Message template",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "telegram.default.message" .}}',
                },
                "disable_notifications": {
                    "description": "Disable telegram notifications",
                    "type": "boolean",
                    "default": False,
                },
                "parse_mode": {
                    "description": "Parse mode for telegram message, supported values are MarkdownV2, Markdown, HTML and empty string for plain text.",  # noqa: E501
                    "type": "string",
                    "enum": ["MarkdownV2", "Markdown", "HTML", ""],
                    "default": "MarkdownV2",
                },
                "http_config": {
                    "description": "The HTTP client's configuration. Defaults to global.http_config.",  # noqa: E501
                    "$ref": "#/definitions/http_config",
                },
            },
            "additionalProperties": False,
        },
        "template_reference": {
            "type": "string",
            "pattern": '^({{\\s)(template\\s)?("[\\w.]*"\\s)?(.[\\w.]*)?(\\s\\|\\s\\w+)?(\\s}})$',
        },
        "time_interval": {
            "description": "A time_interval specifies a named interval of time that may be referenced in the routing tree to mute/activate particular routes for particular times of the day.",  # noqa: E501
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                },
                "time_intervals": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/time_interval_definition"},
                    "additionalItems": False,
                },
            },
            "additionalProperties": False,
            "required": ["name", "time_intervals"],
        },
        "time_interval_definition": {
            "description": "A time_interval contains the actual definition for an interval of time.",  # noqa: E501
            "type": "object",
            "properties": {
                "times": {
                    "description": "A list of time ranges inclusive of the starting time and exclusive of the end time to make it easy to represent times that start/end on hour boundaries.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/time_range"},
                    "additionalItems": False,
                },
                "weekdays": {
                    "description": "A list of days of the week, where the week begins on Sunday and ends on Saturday. Days should be specified by name (e.g. 'Sunday'). For convenience, ranges are also accepted of the form : and are inclusive on both ends. For example: ['monday:wednesday','saturday', 'sunday']",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/weekdays"},
                },
                "days_of_month": {
                    "description": "A list of numerical days in the month. Days begin at 1. Negative values are also accepted which begin at the end of the month, e.g. -1 during January would represent January 31. For example: ['1:5', '-3:-1']. Extending past the start or end of the month will cause it to be clamped. E.g. specifying ['1:31'] during February will clamp the actual end date to 28 or 29 depending on leap years. Inclusive on both ends.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/days_of_month"},
                },
                "months": {
                    "description": " A list of calendar months identified by a case-insensitive name (e.g. 'January') or by number, where January = 1. Ranges are also accepted. For example, ['1:3', 'may:august', 'december']. Inclusive on both ends.",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/months"},
                },
                "years": {
                    "description": "A numerical list of years. Ranges are accepted. For example, ['2020:2022', '2030']",  # noqa: E501
                    "type": "array",
                    "items": {"$ref": "#/definitions/years"},
                },
            },
            "additionalProperties": False,
        },
        "time_range": {
            "description": "Ranges inclusive of the starting time and exclusive of the end time to make it easy to represent times that start/end on hour boundaries. For example, start_time: '17:00' and end_time: '24:00' will begin at 17:00 and finish immediately before 24:00.",  # noqa: E501
            "type": "object",
            "properties": {
                "start_time": {
                    "type": "string",
                    "pattern": "^([0-1]?\\d|2[0-3]):[0-5]\\d$",
                },
                "end_time": {
                    "type": "string",
                    "pattern": "^([0-1]?\\d|2[0-3]):[0-5]\\d$",
                },
            },
            "additionalProperties": False,
            "required": ["start_time", "end_time"],
        },
        "tls_config": {
            "type": "object",
            "properties": {
                "ca_file": {
                    "description": "CA certificate to validate API server certificate with.",
                    "$ref": "#/definitions/filepath",
                },
                "cert_file": {
                    "description": "Certificate file for client cert authentication to the server.",  # noqa: E501
                    "$ref": "#/definitions/filepath",
                },
                "key_file": {
                    "description": "Key file for client cert authentication to the server.",
                    "$ref": "#/definitions/filepath",
                },
                "server_name": {
                    "description": "ServerName extension to indicate the name of the server.",
                    "type": "string",
                },
                "insecure_skip_verify": {
                    "description": "Disable validation of the server certificate.",
                    "type": "boolean",
                    "default": False,
                },
            },
            "additionalProperties": False,
        },
        "url_or_template_ref_value": {
            "oneOf": [
                {"type": "string", "format": "uri-reference"},
                {"$ref": "#/definitions/template_reference"},
            ]
        },
        "victorops_config": {
            "description": "VictorOps notifications are sent out via the VictorOps API.",
            "type": "object",
            "properties": {
                "send_resolved": {
                    "description": "Whether to notify about resolved alerts.",
                    "type": "boolean",
                    "default": True,
                },
                "api_key": {
                    "description": "The API key to use when talking to the VictorOps API. Defaults to global.victorops_api_key.",  # noqa: E501
                    "type": "string",
                },
                "api_url": {
                    "description": "The VictorOps API URL. Defaults to global.victorops_api_url.",
                    "type": "string",
                    "format": "uri-reference",
                },
                "routing_key": {
                    "description": " A key used to map the alert to a team.",
                    "type": "string",
                },
                "message_type": {
                    "description": "Describes the behavior of the alert (CRITICAL, WARNING, INFO).",  # noqa: E501
                    "type": "string",
                    "enum": ["CRITICAL", "WARNING", "INFO"],
                    "default": "CRITICAL",
                },
                "entity_display_name": {
                    "description": "Contains summary of the alerted problem.",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "victorops.default.entity_display_name" . }}',
                },
                "state_message": {
                    "description": "Contains long explanation of the alerted problem.",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "victorops.default.state_message" . }}',
                },
                "monitoring_tool": {
                    "description": "The monitoring tool the state message is from.",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "victorops.default.monitoring_tool" . }}',
                },
                "http_config": {
                    "description": "The HTTP client's configuration. Defaults to global.http_config.",  # noqa: E501
                    "$ref": "#/definitions/http_config",
                },
            },
            "additionalProperties": False,
            "required": ["routing_key"],
        },
        "webhook_config": {
            "description": "The webhook receiver allows configuring a generic receiver.",
            "type": "object",
            "properties": {
                "send_resolved": {
                    "description": "Whether to notify about resolved alerts.",
                    "type": "boolean",
                    "default": True,
                },
                "url": {
                    "description": "The endpoint to send HTTP POST requests to.",
                    "type": "string",
                    "format": "uri-reference",
                },
                "max_alerts": {
                    "description": "The maximum number of alerts to include in a single webhook message. Alerts above this threshold are truncated. When leaving this at its default value of 0, all alerts are included.",  # noqa: E501
                    "type": "number",
                    "default": 0,
                },
                "http_config": {
                    "description": "The HTTP client's configuration. Defaults to global.http_config.",  # noqa: E501
                    "$ref": "#/definitions/http_config",
                },
            },
            "additionalProperties": False,
            "required": ["url"],
        },
        "wechat_config": {
            "description": "WeChat notifications are sent via the WeChat API.",
            "type": "object",
            "properties": {
                "send_resolved": {
                    "description": "Whether to notify about resolved alerts.",
                    "type": "boolean",
                    "default": True,
                },
                "api_secret": {
                    "description": "The API key to use when talking to the WeChat API. Defaults to global.wechat_api_secret.",  # noqa: E501
                    "type": "string",
                },
                "api_url": {
                    "description": "The WeChat API URL. Defaults to global.wechat_api_url.",
                    "type": "string",
                    "format": "uri-reference",
                },
                "corp_id": {
                    "description": "The corp id for authentication. Defaults to global.wechat_api_corp_id.",  # noqa: E501
                    "type": "string",
                },
                "message": {
                    "description": "API request data as defined by the WeChat API.",
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "wechat.default.message" . }}',
                },
                "message_type": {
                    "description": "Type of the message type, supported values are `text` and `markdown`.",  # noqa: E501
                    "type": "string",
                    "enum": ["text", "markdown"],
                    "default": "text",
                },
                "agent_id": {
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "wechat.default.agent_id" . }}',
                },
                "to_user": {
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "wechat.default.to_user" . }}',
                },
                "to_party": {
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "wechat.default.to_party" . }}',
                },
                "to_tag": {
                    "$ref": "#/definitions/string_or_template_ref_value",
                    "default": '{{ template "wechat.default.to_tag" . }}',
                },
            },
            "additionalProperties": False,
        },
        "weekdays": {
            "description": "Days should be specified by name (e.g. 'Sunday'). For convenience, ranges are also accepted of the form : and are inclusive on both ends. Example: 'tuesday:Saturday' or 'Monday'.",  # noqa: E501
            "type": "string",
            "pattern": "^([Mm]onday|[Tt]uesday|[Ww]ednesday|[Tt]hursday|[Ff]riday|[Ss]aturday|[Ss]unday)(:($1))?$",  # noqa: E501
        },
        "years": {
            "description": "A numerical value of years. Ranges are accepted. Ranges are inclusive on both ends. Example: '2020:2022' or '2030'.",  # noqa: E501
            "type": "string",
            "pattern": "^(2\\d\\d\\d)(:[2-9]\\d\\d\\d)?$",
        },
    },
}
DEFAULT_RELATION_NAME = "remote-configurer"
DEFAULT_ALERTMANAGER_CONFIG_FILE_PATH = "/etc/alertmanager/alertmanager.yml"


def load_config_file(path: str) -> dict:
    """Reads given Alertmanager configuration file and turns it into a dictionary.

    Args:
        path: Path to the Alertmanager configuration file

    Returns:
        dict: Alertmanager configuration file in a form of a dictionary
    """
    if os.path.exists(path):
        with open(path, "r") as config_yaml:
            config = yaml.safe_load(config_yaml)
        return config
    else:
        error_msg = "Given Alertmanager config file {} doesn't exist!".format(path)
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)


def load_templates_file(path: str) -> str:
    """Reads given Alertmanager templates file and returns its content in a form of a string.

    Args:
        path: Alertmanager templates file path

    Returns:
        str: Alertmanager templates
    """
    if os.path.exists(path):
        with open(path, "r") as template_file:
            templates = template_file.read()
        return templates
    else:
        logger.warning(
            "Given Alertmanager templates file {} doesn't exist. Skipping...".format(path)
        )
        raise FileNotFoundError


class AlertmanagerRemoteConfigurerProvider(Object):
    """API that manages a provided `alertmanager_remote_configurer` relation.

    The `AlertmanagerRemoteConfigurerProvider` is intended to be used by charms whose workloads
    need to receive data from other charms' workloads over the `alertmanager_remote_configurer`
    interface.

    The `AlertmanagerRemoteConfigurerProvider` object can be instantiated as follows in your charm:

    ```
    from charms.alertmanager_k8s.v0.alertmanager_remote_configurer import (
        AlertmanagerRemoteConfigurerProvider,
    )

    def __init__(self, *args):
        ...
        self.remote_configurer_provider = AlertmanagerRemoteConfigurerProvider(self)
        ...
    ```

    The `AlertmanagerRemoteConfigurerProvider` assumes that, in the `metadata.yaml` of your charm,
    you declare a provided relation as follows:

    ```
    provides:
        remote-configurer:  # Relation name
            interface: alertmanager_remote_configurer  # Relation interface
            limit: 1
    ```

    When `remote-configurer` is created, `AlertmanagerRemoteConfigurerProvider` reads the current
    configuration of the Alertmanager from the specified configuration file and pushes the content
    to the relation data bag. This initial configuration can then be used by the consumer
    of the relation.
    The `AlertmanagerRemoteConfigurerProvider` provides 2 public methods for accessing the data
    from the relation data bag - `config` and `templates`. Typical usage of these methods in the
    provider charm would look something like:

    ```
    def get_config(self, *args):
        ...
        alertmanager_config = self.remote_configurer_provider.config()
        ...
        self.container.push("/alertmanager/config/file.yml", alertmanager_config)
        ...
    ```

    ```
    def get_templates(self, *args):
        ...
        alertmanager_templates = self.remote_configurer_provider.templates()
        ...
        self.container.push("/alertmanager/templates/file.tmpl", alertmanager_templates)
        ...
    ```

    Separation of the main configuration and the templates is dictated by the assumption that
    the default provider of the `alertmanager_remote_configurer` relation will be
    `alertmanager-k8s` charm, which requires such separation.

    The `AlertmanagerRemoteConfigurerProvider` also provides a JSON Schema of the Alertmanager
    configuration. Before returning configuration to the provider charm,
    `AlertmanagerRemoteConfigurerProvider` validates it. Configuration that passed the validation
    is returned to the provider charm. Invalid configurations are discarded (empty dict
    is returned to the provider charm) and the relevant error message is logged.
    """

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
        config_file_path: str = DEFAULT_ALERTMANAGER_CONFIG_FILE_PATH,
        api_address: str = "http://localhost:9093",
    ):
        """API that manages a provided `remote-configurer` relation.

        Args:
            charm: The charm object that instantiated this class.
            relation_name: Name of the relation with the `alertmanager_remote_configurer` interface
                as defined in metadata.yaml. Defaults to `remote-configurer`.
            config_file_path: The path to the Alertmanager configuration file. Defaults
                to `/etc/alertmanager/alertmanager.yml`.
            api_address: Defaults to `http://localhost:9093`
        """
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._config_file_path = config_file_path
        self.api_address = api_address

        on_relation = self._charm.on[self._relation_name]

        self.framework.observe(on_relation.relation_joined, self._on_relation_joined)

    def _on_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Event handler for RelationJoinedEvent.

        Args:
            event: Juju RelationJoinedEvent

        Returns:
            None
        """
        self.load_initial_alertmanager_config_to_relation_data_bag(event)

    def load_initial_alertmanager_config_to_relation_data_bag(
        self, event: RelationJoinedEvent
    ) -> None:
        """Loads current Alertmanager configuration to the relation data bag.

        Reads current Alertmanager configuration from alertmanager.yml and puts the content
        inside relation data bag. If needed, it can be used by `alertmanager-remote-configurer`
        consumer as a starting point for generating custom configuration.

        Args:
            event: Juju RelationJoinedEvent

        Returns:
            None
        """
        if not self._charm.unit.is_leader():
            return
        alertmanager_config = self._get_current_config()
        event.relation.data[self._charm.app]["alertmanager_config"] = json.dumps(
            alertmanager_config
        )

    def config(self) -> dict:
        """Returns Alertmanager configuration sent inside the relation data bag.

        If the `alertmanager-remote-configurer` relation exists, takes the Alertmanager
        configuration provided in the relation data bag and returns it in a form of a dictionary
        if configuration passes the validation against the Alertmanager config schema.
        If configuration fails the validation, error is logged and config is rejected (empty config
        is returned).

        Returns:
            dict: Alertmanager configuration dictionary
        """
        config = {}
        remote_configurer_relation = self._charm.model.get_relation(self._relation_name)
        if remote_configurer_relation:
            try:
                raw_config = remote_configurer_relation.data[remote_configurer_relation.app][  # type: ignore[index]  # noqa: E501
                    "alertmanager_config"
                ]
                if self._config_is_valid(json.loads(raw_config)):
                    config = raw_config
                else:
                    logger.error("Config validation error.")
            except KeyError:
                logger.warning(
                    "Remote config provider relation exists, but no config has been provided."
                )
        return config

    def templates(self) -> list:
        """Returns Alertmanager templates sent inside the relation data bag.

        If the `alertmanager-remote-configurer` relation exists and the relation data bag contains
        Alertmanager templates, returns the templates in the form of a list.

        Returns:
            list: Alertmanager templates
        """
        templates = []
        remote_configurer_relation = self._charm.model.get_relation(self._relation_name)
        if remote_configurer_relation:
            try:
                templates_raw = remote_configurer_relation.data[remote_configurer_relation.app][  # type: ignore[index]  # noqa: E501
                    "alertmanager_templates"
                ]
                templates = json.loads(templates_raw)
            except KeyError:
                logger.warning(
                    "Remote config provider relation exists, but no templates have been provided."
                )
        return templates

    @staticmethod
    def _config_is_valid(config: dict) -> bool:
        """Validates Alertmanager configuration.

        Uses JSON Schema validator to check whether the Alertmanager configuration provided
        by the `alertmanager-remote-configurer` consumer is valid.

        Args:
            config: Alertmanager configuration JSON

        Returns:
            bool: True/False depending on the configuration validity
        """
        try:
            validate(instance=config, schema=ALERTMANAGER_CONFIG_JSON_SCHEMA)
            return True
        except exceptions.ValidationError:
            return False

    def _get_current_config(self) -> str:
        """Gets current configuration of the Alertmanager.

        Uses Alertmanager's API to get the current configuration.

        Returns:
            str: Alertmanager configuration
        """
        config_endpoint = "api/v2/status"
        url = "{}/{}".format(self.api_address, config_endpoint)
        response = requests.get(url)
        return response.json()["config"]["original"] if response.status_code == 200 else ""


class AlertmanagerRemoteConfigurerConsumer(Object):
    """API that manages a required `alertmanager_remote_configurer` relation.

    The `AlertmanagerRemoteConfigurerConsumer` is intended to be used by charms that need to push
    data to other charms over the `alertmanager_remote_configurer` interface.

    The `AlertmanagerRemoteConfigurerConsumer` object can be instantiated as follows in your charm:

    ```
    from charms.alertmanager_k8s.v0.alertmanager_remote_configurer import
        AlertmanagerRemoteConfigurerConsumer,
    )

    def __init__(self, *args):
        ...
        self.remote_configurer_consumer = AlertmanagerRemoteConfigurerConsumer(self)
        ...
    ```

    The `AlertmanagerRemoteConfigurerConsumer` assumes that, in the `metadata.yaml` of your charm,
    you declare a required relation as follows:

    ```
    requires:
        remote-configurer:  # Relation name
            interface: alertmanager_remote_configurer  # Relation interface
    ```

    The `AlertmanagerRemoteConfigurerConsumer` provides handling of the most relevant charm
    lifecycle events. On each of the defined Juju events, Alertmanager configuration and templates
    from a specified file will be pushed to the relation data bag.
    Inside the relation data bag, Alertmanager configuration will be stored under
    `alertmanager_configuration` key, while the templates under the `alertmanager_templates` key.
    Separation of the main configuration and the templates is dictated by the assumption that
    the default provider of the `alertmanager_remote_configurer` relation will be
    `alertmanager-k8s` charm, which requires such separation.
    """

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
        config_file_path: str = DEFAULT_ALERTMANAGER_CONFIG_FILE_PATH,
    ):
        """API that manages a required `remote-configurer` relation.

        Args:
            charm: The charm object that instantiated this class.
            relation_name: Name of the relation with the `alertmanager_remote_configurer` interface
                as defined in metadata.yaml. Defaults to `remote-configurer`.
            config_file_path: The path to the Alertmanager configuration file. Defaults
                to `/etc/alertmanager/alertmanager.yml`.
        """
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._config_file_path = config_file_path

        on_relation = self._charm.on[self._relation_name]

        self.framework.observe(on_relation.relation_joined, self._on_relation_event)
        self.framework.observe(on_relation.relation_changed, self._on_relation_event)
        self.framework.observe(self._charm.on.upgrade_charm, self._on_upgrade_charm)

    def _on_relation_event(self, event: Union[RelationJoinedEvent, RelationChangedEvent]) -> None:
        """Event handler for remote configurer's relation events.

        Takes care of pushing Alertmanager configuration to the relation data bag.

        Args:
            event: Juju event

        Returns:
             None
        """
        if not self._charm.unit.is_leader():
            return
        self._update_relation_databag(event.relation)

    def _on_upgrade_charm(self, _) -> None:
        """Event handler for charm upgrade event.

        Takes care of pushing Alertmanager configuration to the relation data bag.

        Returns:
             None
        """
        if not self._charm.unit.is_leader():
            return
        relation = self.model.get_relation(self._relation_name)
        self._update_relation_databag(relation)  # type: ignore[arg-type]

    def _update_relation_databag(self, relation: Relation) -> None:
        try:
            self._config = load_config_file(self._config_file_path)
            self._templates = self._get_templates(self._config)
            relation.data[self._charm.app]["alertmanager_config"] = json.dumps(self._config)
            relation.data[self._charm.app]["alertmanager_templates"] = json.dumps(self._templates)
        except FileNotFoundError as e:
            self._charm.unit.status = BlockedStatus(str(e))

    @staticmethod
    def _get_templates(config: dict) -> list:
        """Prepares templates data to be put in a relation data bag.

        If the main config file contains templates section, content of the files specified in this
        section will be concatenated. At the same time, templates section will be removed from
        the main config, as alertmanager-k8s-operator charm doesn't tolerate it.

        Args:
            config: Alertmanager config

        Returns:
            list: List of templates
        """
        templates = []
        if config.get("templates", []):
            for file in config.pop("templates"):
                try:
                    templates.append(load_templates_file(file))
                except FileNotFoundError:
                    continue
        return templates
