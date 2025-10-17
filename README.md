# HAnS

HAnS (derived from the German "Hochschul-Assistenz-System") is a learning experience platform which collects teaching
and learning materials of different subjects.

It processes the audio or video materials and creates a search index for each media file.

The users are able to search for exact words or topics in the media content and can directly skip forward to
the exact position of the searched topic or word on the selected media file.

A tutor will be established which applies predefined templates to generate exercises and learning goal controls
for the uploaded media files.

## Architecture

HAnS uses multiple docker containers.
The web [frontend](OVERVIEW.md#frontend) is hosted in a docker container using [Apache](https://apache.org/).
The service [backend](OVERVIEW.md#backend) consists of multiple containers including databases and search engine.
The processing of the media files is organized by [Apache Airflow](https://airflow.apache.org/) in workflows
consisting of multiple processing tasks in the [ml-backend](OVERVIEW.md#machine-learning-backend-ml-backend).
For more details see [Architecture Overview](OVERVIEW.md#architecture-overview).

For a hosting and security scenario see [Hosting and Security](HOSTING.md#hosting-and-security).

## Processing

HAnS uses [ml-backend](OVERVIEW.md#machine-learning-backend-ml-backend) powered by
[Apache Airflow](https://airflow.apache.org/) for processing the audio or video materials and the related slides.
For more details see [Processing Sequence Example](SEQUENCES.md#processing).

## Getting Started

### Prerequisites

- 64-bit operating system
  - Linux distribution, e.g. Debian, Ubuntu or other
    - Recommended [Ubuntu Server 20.04 LTS](https://ubuntu.com/download/server)
- [Python 3](https://www.python.org/)
  - Python is required for configuration, please ensure python3 (>=3.5) is installed on your system
  - See the [official python download page](https://www.python.org/downloads/)
- [openssl](https://www.openssl.org/)
  - Generation of authentication key pairs for [PyJWT](https://pyjwt.readthedocs.io/en/latest/algorithms.html)
- [Docker](https://www.docker.com/)
  - Check [supported Docker server platforms](https://docs.docker.com/engine/install/#server)
  - Recommended is to [install Docker on Ubuntu](https://docs.docker.com/engine/install/ubuntu/),
    see [Docker OS requirements](https://docs.docker.com/engine/install/ubuntu/#os-requirements)
- [docker compose](https://docs.docker.com/compose/)
  - See instructions to [Install Docker Compose](https://docs.docker.com/compose/install/)
- [Git](https://git-scm.com/)
  - See [installing Git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)
    for instructions how to install Git on your server
- [Git Large File Storage (LFS)](https://git-lfs.github.com/)
  - See [Getting Started](https://git-lfs.github.com/), you only need to run this once per user account on your server:

  ```bash
  git lfs install
  ```

### Installation

- Open a linux shell

- Clone the git repository

```bash
git clone https://github.com/th-nuernberg/hans.git
```

- Follow the [SETUP](./SETUP.md) instructions to configure HAnS.

- Use `start.cmd` to start all docker containers on one machine (and grab a coffee):

```bash
cd hans
./start.cmd
```

### Testing

- Use `start.cmd -t` to start all docker containers and execute tests on one machine (and grab a coffee):

```bash
cd hans
./start.cmd -t
```

### Debugging

- Use `start.cmd -d` to start additional docker containers that are helpful for debugging
  (e.g. [adminer](./common/adminer/Dockerfile)):

```bash
cd hans
./start.cmd -d
```
Hint: if `start.cmd` is used with the test flag `-t`, the debug flag will be ignored

### Troubleshooting

- If you already cloned the repository and not installed `git-lfs` beforehand use `git lfs pull` to correctly
  initialize your local repository:

```bash
cd hans
git lfs pull
```
