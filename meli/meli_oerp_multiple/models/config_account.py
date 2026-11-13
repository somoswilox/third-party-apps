# -*- coding: utf-8 -*-
# un caso: `config` llega como mercadolibre.configuration o, cuando el llamador hizo
# `config = config or company`, como res.company (que no tiene `accounts` ni `company_id`).
# Estos helpers resuelven cuenta y compania sin AttributeError y sin elegir una cuenta
# al azar cuando la compania tiene varias conexiones.


def meli_config_account(config, fallback=None):
    """mercadolibre.account de `config`, o `fallback` si no se puede resolver sin ambiguedad."""
    if config:
        if 'accounts' in config._fields and config.accounts:
            return config.accounts[0]
        if 'mercadolibre_connections' in config._fields and len(config.mercadolibre_connections) == 1:
            return config.mercadolibre_connections
    return fallback


def meli_config_company(config, account=None):
    """res.company de `config` (configuracion o compania), o la de `account`."""
    if config:
        if config._name == 'res.company':
            return config
        if 'company_id' in config._fields and config.company_id:
            return config.company_id
    return account and account.company_id
