import os
import asyncio

from ps2.symbol_table.environment import Environment
from ps2.scan.scanner import Scanner
from ps2.parser.parser import Parser
from ps2.interpret.interpretor import Interpretor

class PS2:

    running_process = None
    hadError = False

    async def report(line, where, message):
        if line is None:
            await PS2.print(f"{where} error: {message}", error=True)
        else:
            await PS2.print(f"[line {line}] {where} error: {message}", error=True)

        PS2.hadError = True

    # Run Interpretor from a file
    async def runFile(fileName, timeout):
        try:
            with open(fileName) as file:
                lines = file.readlines()

                start_dir = os.getcwd()

                given_dir = os.path.dirname(fileName)
                new_dir   = os.path.realpath(os.path.join(start_dir, given_dir))

                os.chdir(new_dir)

                PS2.running_process = asyncio.create_task(PS2.runWithTimeout(lines, timeout))

                while not PS2.running_process.done() and not PS2.running_process.cancelled():
                    await asyncio.sleep(0.1)

                os.chdir(start_dir)
        except FileNotFoundError:
            print(f"Error: script '{fileName}' does not exist")

    async def runWithTimeout(lines, timeout):
        try:
            await asyncio.wait_for(PS2.run("".join(lines)), timeout=timeout)
        except asyncio.TimeoutError:
            await PS2.report(None, "Timeout", f"Process exceeded {timeout}s limit")

    async def run(source):

        try:
            tokens     = Scanner(source).scanTokens()        
            statements = Parser(tokens).parse()
                
        except SyntaxError as e:
            await PS2.report(e.msg[0], "Syntax", e.msg[1])

        if not PS2.hadError:
            try:
                await Interpretor(statements).interpret()
            except RuntimeError as e:
                await PS2.report(e.args[0][0], "Runtime", e.args[0][1])
                PS2.hadError = False
                
        else:
            PS2.hadError = False

