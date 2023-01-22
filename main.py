import os
import json
import string
import random
import shutil
import asyncio
import websockets

from datetime import datetime

from ps2 import statement
from ps2.app import PS2 as PS2


FOLDER    = "tmp"
TIMEOUT   = 60
run_queue = []
waiting_for_input = {
    "key":     None,
    "text":    None,
    "waiting": False
}


async def input_override(*args, **kwargs):
    global waiting_for_input

    item = run_queue[0]
    await item["ws"].send(json.dumps({ "type": "INPUT" }))

    waiting_for_input = {
        "key":     item["key"],
        "text":    None,
        "waiting": True
    }

    while waiting_for_input["text"] is None:
        await asyncio.sleep(0.01)

    text = waiting_for_input["text"]
    waiting_for_input = {
        "key":     None,
        "text":    None,
        "waiting": False
    }

    return text


async def print_override(*args, sep=' ', end='\n', file=None, error=False):
    await run_queue[0]["ws"].send(json.dumps({
        "type": "ERROR" if error else "OUTPUT",
        "text": " ".join(list(map(str, args))),
        "end": end
    }))

PS2.print                 = print_override
statement.statement.input = input_override
statement.statement.print = print_override


def random_string():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))


def get_run_queue_index(key):
    for i in range(len(run_queue)):
        if run_queue[i]["key"] == key:
            return i


async def update_client_queue_positions():
    for i in range(1, len(run_queue)):
        await run_queue[i]["ws"].send(json.dumps({
            "type": "QUEUE_UPDATE",
            "position": i
        }))


def clean_up_files():
    for filename in os.listdir(FOLDER):
        file_path = os.path.join(FOLDER, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print('Failed to delete %s. Reason: %s' % (file_path, e))


async def run(files, entrypoint, ws):
    global running_process

    await ws.send(json.dumps({ "type": "RUNNING" }))

    for name, content in files.items():
        if "/" not in name:
            with open(f"tmp/{name}", "w+") as f:
                f.write(content)

    await PS2.runFile(f"{FOLDER}/{entrypoint}", TIMEOUT)

    files = {}
    for filename in os.listdir(FOLDER):
        with open(f"{FOLDER}/{filename}") as f:
            files[filename] = f.read()

    clean_up_files()

    await ws.send(json.dumps({
        "type": "SUCCESS",
        "files": files
    }))


async def add_to_queue(ws, msg):
    key = random_string()
    while get_run_queue_index(key) is not None:
        key = random_string()

    run_queue.append({
        "ws":         ws,
        "key":        key,
        "files":      msg["files"],
        "entrypoint": msg["entrypoint"]
    })

    await ws.send(json.dumps({
        "key":       key,
        "type":     "QUEUED",
        "position": len(run_queue) - 1
    }))


def log(msg_type):
    colour = "\033[31m" if msg_type == "UNKNOWN" else "\033[32m"
    print(f"[{colour}{msg_type}\033[0m] {datetime.now()}")

async def handle_messages(ws):
    global waiting_for_input

    async for message in ws:
        msg = json.loads(message)

        if "type" not in msg or msg["type"] not in ["RUN", "INPUT", "STOP"]:
            log("UNKNOWN")
            continue

        log(msg["type"])

        if msg["type"] == "RUN" and "files" in msg:
            await add_to_queue(ws, msg)
        elif (
                msg["type"] == "INPUT" and waiting_for_input["waiting"] and
                "key" in msg and waiting_for_input["key"] == msg["key"] and "text" in msg
        ):
            waiting_for_input["text"] = msg["text"]
        elif msg["type"] == "STOP" and "key" in msg:
            i = get_run_queue_index(msg["key"])
            if i is not None:
                if i == 0 and PS2.running_process is not None:
                    PS2.running_process.cancel()

                if i != 0:
                    run_queue.pop(i)
                    await update_client_queue_positions()


async def eval_queue():
    global run_queue, running_process

    while True:
        if len(run_queue) > 0:
            new_queue = []
            for item in run_queue:
                try:
                    await item["ws"].send(json.dumps({ "type": "PING" }))
                except websockets.exceptions.ConnectionClosed:
                    continue
                else:
                    new_queue.append(item)

            run_queue = new_queue

            await update_client_queue_positions()

            entry = run_queue[0]

            try:
                await run(entry["files"], entry["entrypoint"], entry["ws"])
            except websockets.exceptions.ConnectionClosed:
                clean_up_files()

            run_queue.pop(0)
        else:
            await asyncio.sleep(0.1)


async def main():
    asyncio.create_task(eval_queue())

    async with websockets.serve(handle_messages, "localhost", 5000):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
