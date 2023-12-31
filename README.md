# Steganography Botnet POC

This project was created as a proof of concept to demonstrate the use of steganography in a botnet.
The malware uses the Dropbox API to communicate with the C&C server and hides the communication in cat images from https://cataas.com/.
This project is to be used for study purposes only.

## Prerequisites

The implementation assumes the use of **Python 3.10** and the installation of the necessary packages from **requirements.txt** file.

### Installation of required packages

```bash
pip install -r requirements.txt
```

## Bot

The Bot can be started with the following command:

```bash
DROPBOX_TOKEN=<YOUR DROPBOX ACCESS TOKEN> python3 bot.py
```

The bot does not support any user interaction and runs independently.
The only way to control the bot is through the Controller.

## Controller

The Controller can be started with the following command:

```bash
DROPBOX_TOKEN=<YOUR DROPBOX ACCESS TOKEN> python3 controller.py
```

### Example usage

After starting the Controller, all active Bots will be listed and the user can choose which Bot to control.

```
Waiting for bots to connect...

The following bots are available:
[0] veronica915
[1] sebastian762
[2] maria122

Choose bot to command:
```

User input: `2`

```
The following commands are available:
[0] Run script
[1] Download file

Choose command to issue:
```

User input: `0`

```
Enter the script to be run:
```

User input: `whoami` (or any other bash script)

```
Waiting for command to be executed... (might take up to 15 seconds)

> whoami
pepino
```
