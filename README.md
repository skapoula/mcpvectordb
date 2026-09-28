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

## Add your documents

Your library starts empty. Load documents in one of these ways. Always give the **full
path** to the file or folder; the server reads it from your disk, so you do not attach
anything to the chat.

### Ask Claude (easiest)

In a Claude Desktop conversation, ask in plain language:

- One file: *"Add `C:\Users\me\Documents\contract.pdf` to my library."*
- A whole folder, including its subfolders:
  *"Add every document in `/Users/me/Documents/Reports` to a library called reports."*
- A web page: *"Add https://example.com/guide to a library called research."*

Claude replies with how many documents were added. A folder can take a while: each file
is read, split into passages, and indexed. Files that cannot be read are listed as
failed; the rest are still added.

**Libraries** are named collections, such as `work` or `research`. If you do not name
one, documents go into `default`. You can later search one library or all of them.

### Load a large folder from the command line

For hundreds of files, loading outside Claude avoids a long wait in the chat. In
PowerShell or Terminal, go to the mcpvectordb folder and run (Windows first, then macOS
or Linux):

```powershell
uv run mcpvectordb-ingest "C:\Users\me\Documents\Reports" --library reports
```

```bash
uv run mcpvectordb-ingest "/Users/me/Documents/Reports" --library reports
```

When it finishes, it prints how many files were added, skipped or failed, and why each
failure happened.

You can list several files or folders. Add `--no-recursive` to skip subfolders.
Documents loaded this way appear in Claude straight away.

### Updating documents

Adding the same file again is safe. An unchanged file is skipped. A changed file
replaces its old version, so run the same request or command again after you edit your
documents.

## Supported file types

| Works well | File types |
| --- | --- |
| PDF | `.pdf` (must contain text; see below) |
| Word | `.docx` |
| PowerPoint | `.pptx` |
| Excel | `.xlsx`, `.xls` |
| Web pages | `.html`, `.htm`, or any `http`/`https` link |
| Text and data | `.txt`, `.md`, `.csv`, `.json`, `.xml` |
| Archives | `.zip` containing any of the above |

Not supported in practice:

- **Scanned PDFs and photos** (`.jpg`, `.png`, and other images): there is no text
  recognition (OCR), so pages that are pictures of text produce nothing. Run them
  through an OCR tool first, or copy the text into a `.txt` file.
- **Old Office formats** (`.doc`, `.ppt`): open them in Word or PowerPoint and save as
  `.docx` or `.pptx`.
- **Audio** (`.mp3`, `.wav`, `.m4a`, `.ogg`): transcription would send the recording to
  Google's speech service, so audio is refused. Transcribe it on your computer and add
  the text instead.

## Ask questions

Once documents are loaded, ask Claude about them:

- *"Search my documents for the notice period in the contract."*
- *"What do my reports say about Q3 revenue? Only search the reports library."*
- *"Which documents are in my library?"*
- *"Remove contract.pdf from my library."*

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
