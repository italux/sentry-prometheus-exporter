# Welcome to Sentry Prometheus Exporter 👋
![Version](https://img.shields.io/github/v/tag/italux/sentry-prometheus-exporter)
[![License: GNU General Public License v2.0](https://img.shields.io/github/license/italux/sentry-prometheus-exporter)](https://github.com/italux/sentry-prometheus-exporter/blob/master/LICENSE)
![Dockehub Build](https://img.shields.io/docker/cloud/automated/italux/sentry-prometheus-exporter)
![Dockehub build status](https://img.shields.io/docker/cloud/build/italux/sentry-prometheus-exporter)

> Export sentry project's metrics consistent with the Prometheus exposition formats

* [Getting Started](#getting-started)
  + [Prerequisites](#prerequisites)
  + [Install](#install)
  + [Run](#run)
  + [Docker](#docker)
* [Important Notes](#---important-notes)
  + [Limitations](#limitations)
  + [Recomendations & Tips](#recomendations---tips)
* [Documentation](#---documentation)
* [Contributing](#---contributing)
* [License](#---license)
* [Show your support](#show-your-support)
* [Author](#author)

## Getting Started

### Prerequisites

- python >= 3.7.9

### Install
```sh
pip install -r requirements.txt
```

### Run
```sh
export SENTRY_BASE_URL="https://sentry.io/api/0/"
export SENTRY_AUTH_TOKEN="[REPLACE_TOKEN]"
export SENTRY_EXPORTER_ORG="[organization_slug]"
```
```sh
python exporter.py
```

### Docker

```sh
docker-compose build
```
```sh
docker-compose up -d
```

## ⚠️ Important Notes

### Limitations
- **Performance**: The exporter is serial, if your organization has a high number of issues & events you may experience `Context Deadline Exceeded` error during a Prometheus scrape

### Recomendations & Tips
- Use `scrape_interval: 5m` minimum.
> This value will be defined by the number of new issues and events\
> higher number of events will take more time
- Use a high `scrape_timeout` for the exporter job
> General recomendation is to set `scrape_interval - 1` (i.e.: `4m`)

## 📒 Documentation

https://italux.github.io/sentry-prometheus-exporter/

## 🤝 Contributing

Contributions, issues and feature requests are welcome!

- Please check the [Contributing Guide](https://github.com/italux/sentry-prometheus-exporter/blob/master/CONTRIBUTING.md)
- Feel free to check [issues page](https://github.com/italux/sentry-prometheus-exporter/issues). 


## 📝 License

Copyright © 2021 [Italo Santos](https://github.com/italux).

This project is [GNU General Public License v2.0](https://github.com/italux/sentry-prometheus-exporter/blob/master/LICENSE) licensed.

## Show your support

Give a ⭐️ if this project helped you!

## Author

👤 **Italo Santos**

* Website: http://italosantos.com.br
* Twitter: [@italux](https://twitter.com/italux)
* Github: [@italux](https://github.com/italux)
* LinkedIn: [@italosantos](https://linkedin.com/in/italosantos)

***
_This README was generated with by [readme-md-generator](https://github.com/kefranabg/readme-md-generator)_
