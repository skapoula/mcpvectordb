# mcpvectordb

Let Claude search your own documents. Add PDFs, Word files, slides, spreadsheets or web
pages to a private library on your computer, then ask Claude questions about them in any
Claude Desktop conversation.

Your documents and the search index stay on your machine. No account or cloud database
is needed.

## What you need

- [Claude Desktop](https://claude.ai/download)
- About 2 GB of free disk space (the search model alone is about 600 MB)
- An internet connection during setup only
- **Windows only:** the
  [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)

## Install

### 1. Install uv

mcpvectordb uses a small tool called **uv** to set itself up. It downloads the right
version of Python for you.

- **Windows:** open **PowerShell** and run:

  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

- **macOS or Linux:** open **Terminal** and run:

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

Close the window and open a new one so the `uv` command is found.

### 2. Download mcpvectordb

Go to <https://github.com/skapoula/mcpvectordb>, click **Code → Download ZIP**, and
unzip it somewhere permanent, such as your Documents folder. Do not move the folder
afterwards; Claude Desktop starts the server from there.

If you use git, you can clone it instead:

```bash
git clone https://github.com/skapoula/mcpvectordb.git
```

### 3. Run the setup

In PowerShell or Terminal, go into the folder you unzipped, then run the setup for your
system. It installs everything, downloads the search model, and prints a block of
settings for Claude Desktop. It takes a few minutes the first time.

- **Windows:**

  ```powershell
  cd $HOME\Documents\mcpvectordb
  powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
  ```

- **Linux:**

  ```bash
  cd ~/Documents/mcpvectordb
  bash scripts/setup-linux.sh
  ```

- **macOS** (there is no setup script yet, so run these three commands):

  ```bash
  cd ~/Documents/mcpvectordb
  uv sync
  uv run mcpvectordb-download-model
  ```

  Then run `which uv` and note the path it prints (for example
  `/Users/you/.local/bin/uv`). You need it in the next step.

Change `Documents/mcpvectordb` if you unzipped the folder somewhere else. A ZIP download
may be named `mcpvectordb-master`.

### 4. Connect Claude Desktop

1. In Claude Desktop, open **Settings → Developer → Edit Config**. This opens
   `claude_desktop_config.json`.
2. **Windows or Linux:** paste the block the setup script printed.

   **macOS:** paste this, replacing the two paths with your uv path and your folder:

   ```json
   {
     "mcpServers": {
       "mcpvectordb": {
         "command": "/Users/you/.local/bin/uv",
         "args": [
           "run",
           "--directory",
           "/Users/you/Documents/mcpvectordb",
           "mcpvectordb"
         ]
       }
     }
   }
   ```

   If the file already has an `"mcpServers"` section, add the `"mcpvectordb": { … }`
   entry inside it instead of pasting a second one.

3. Save the file and **quit Claude Desktop completely**, then open it again. Closing
   the window is not enough.

## Check that it works

Start a new conversation in Claude Desktop and ask:

> List my mcpvectordb libraries.

Claude answers that there are no libraries yet. That means the connection works.

## Use it

Ask Claude in plain language. For example:

- _"Add `C:\Users\me\Documents\contract.pdf` to my library."_
- _"Add the page https://example.com/guide to a library called research."_
- _"Search my documents for the notice period in the contract."_
- _"Which documents are in my library?"_

Give the full path to a file on your computer. The server reads the file itself, so
you do not need to attach it to the chat.

## If something goes wrong

| Problem                                  | What to do                                                                                           |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Claude shows no mcpvectordb tools        | Quit Claude Desktop completely and reopen it. Check the config file for a missing comma or bracket.  |
| Setup says `uv` is not found             | Open a new PowerShell or Terminal window after installing uv, then run the setup again.              |
| Windows says running scripts is disabled | Use the exact `powershell -ExecutionPolicy Bypass -File …` command from step 3.                      |
| A file cannot be added                   | Check the path is complete and the file is a supported type. Scanned PDFs without text may not work. |

## More options

- [Full installation guide](docs/installation.md): containers, hosted servers, and
  settings
- [Windows guide](docs/windows-setup.md) and [Linux guide](docs/linux-setup.md),
  including a standalone app that needs no Python
- [Documentation index](docs/README.md): user guide, tool reference, and contributing
