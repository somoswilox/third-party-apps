# Odoo Connector API (OCAPI)

**Module:** `odoo_connector_api`
**Version:** 18.0.26.6
**Author:** Moldeo Interactive
**License:** GPL-3
**Category:** Sales

## Resumen

OCAPI (Odoo Connector API) es el modulo base de conectores de Moldeo Interactive. Provee la infraestructura fundamental para conectar Odoo con plataformas externas de e-commerce, marketplaces y servicios de fulfillment.

OCAPI define los modelos base de **cuentas de conexion**, **bindings de productos y ordenes**, **configuraciones**, **notificaciones** y **KPIs** que luego son extendidos por cada conector especifico.

## Arquitectura de Modulos Derivados

```
odoo_connector_api (OCAPI Base)
|
|-- Conectores de Marketplace
|   |-- meli_oerp + meli_oerp_multiple  --> mercadolibre.account
|   |-- odoo_connector_api_producteca   --> producteca.account
|   |-- odoo_connector_api_ldps         --> ldps.account
|
|-- Fulfillment
|   |-- odoo_connector_api_fulfillment       --> fulfillment.account
|   |-- odoo_connector_api_fulfillment_sync
|   |-- odoo_connector_api_fulfillment_portal
|   |-- odoo_connector_api_fulfillment_helpdesk
|   |-- odoo_connector_api_fulfillment_project
|
|-- Herramientas
|   |-- ocapi_data_cleanup              --> Limpieza remota base
|   |-- meli_oerp_data_cleanup          --> Limpieza MercadoLibre
|
|-- Publicacion
|   |-- odoo_moldeo_folio               --> Portfolio y publicacion multicanal
```

## Modelos Principales

### `ocapi.connection.account`
Modelo central de cuenta de conexion. Define credenciales (client_id, secret_key, access_token), estado de conexion, configuracion asociada y KPIs. Todos los conectores heredan de este modelo.

### `ocapi.connection.binding`
Modelo base de binding que asocia objetos de Odoo (productos, ordenes, clientes) con sus equivalentes en plataformas externas. Define `connection_account`, `conn_id`, `conn_variation_id`.

### `ocapi.connection.configuration`
Parametros de configuracion para cada cuenta: modo (produccion/test), importacion/publicacion de ventas, productos, precios, stock, warehouses, listas de precio.

### `ocapi.connection.notification`
Manejo de notificaciones entrantes (webhooks). Estados: RECEIVED, PROCESSING, FAILED, SUCCESS.

### `ocapi.connection.credential`
Almacenamiento de credenciales reutilizables.

## API REST

| Endpoint | Metodo | Descripcion |
|----------|--------|-------------|
| `/ocapi/<connector>/auth` | POST | Autenticacion, retorna access token |
| `/ocapi/<connector>/connection` | POST/GET | Info de conexion por token |
| `/ocapi/<connector>/<channel>/status` | POST/GET | Estado de conexion |
| `/ocapi/<connector>/catalog` | POST/GET | Listado de catalogo |
| `/ocapi/<connector>/pricestock` | POST | Precios y stock |
| `/ocapi/<connector>/sales` | POST | Importar ordenes de venta |
| `/ocapi/<connector>/img/<productid>` | GET | Imagen de producto |
| `/ocapi/<connector>/githook` | POST/GET | Webhook de GitHub |

## Herencia de Cuentas

| Modelo Hijo | Hereda de | Conector |
|-------------|-----------|----------|
| `mercadolibre.account` | `ocapi.connection.account` | MercadoLibre |
| `producteca.account` | `ocapi.connection.account` | Producteca |
| `fulfillment.account` | `ocapi.connection.account` | Fulfillment (OFF) |
| `ldps.account` | `ocapi.connection.account` | LDPS |

## Dependencias

- `base`
- `product`
- `sale_management`
- `stock`

## Documentacion

Consultar la carpeta [`docs/`](docs/) para documentacion detallada:

- [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) - Arquitectura general del ecosistema OCAPI
- [`MENU_UNIFICATION.md`](docs/MENU_UNIFICATION.md) - Plan de unificacion de menues bajo OCAPI
- [`ACCOUNT_HIERARCHY.md`](docs/ACCOUNT_HIERARCHY.md) - Jerarquia de cuentas y metodos genericos
- [`GENERIC_PUBLISHING.md`](docs/GENERIC_PUBLISHING.md) - Plan de publicacion generica via OCAPI
- [`NATIVE_CONNECTORS.md`](docs/NATIVE_CONNECTORS.md) - Integracion de conectores nativos de Odoo (Amazon, eBay) via bridges
- [`ROADMAP.md`](docs/ROADMAP.md) - Hoja de ruta de desarrollo (10 fases)

## Autores

**Autor Original y Lider de Desarrollo**
Fabricio Costa (fabricio.costa@moldeointeractive.com.ar)

**Moldeo Interactive** - https://www.moldeointeractive.com
