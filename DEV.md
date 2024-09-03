# DEV

We recommend the usage of the provided devcontainer with VSCode to develop
FoodVibes.

## Step-by-step guide

### 1- Clone the repository and open it in a managed device

Once you cloned the repository, open the folder using a Microsoft
managed machine (windows or WSL). You will also need to have docker installed on
your system.

### 2- Install devcontainer extension

[Here](https://code.visualstudio.com/docs/devcontainers/containers) you will find instructions on how to install devcontainers on VSCode.

Usually you only need to search the Dev Containers extension on the extensions pane and install it. Once the extension is installed, you can open the VSCode command pallete `Ctrl` + `Shift` + `P`, type `Dev
Containers: Open Folder in Container` and select the repository root.

Once you do it, VSCode will create the dev container to you.

### 3- Log into your azure account

Open the terminal and log into your azure account.

```bash
az login
```

### 4- Start FoodVibes services

Once your user is logged, open two terminal instances and start the following services.

**4.1- Terminal 2: FoodVibes Backend**

Open a new terminal and issue the following command to start the FoodVibes backend.

```bash
(foodvibes-all-in-one) vscode [ /workspaces/FoodVibes ]$ python app.py
2024-06-26 01:38:27,971 - FoodVibes API - INFO - started (app.py:26)
INFO:     Started server process [79819]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:7478 (Press CTRL+C to quit)
```

**4.2- Terminal 3: UI**

Finally, in a third Terminal window on VSCode, start the ui by issuing the following commands:

Install yarn (just once).

```bash
(foodvibes-all-in-one) vscode [ /workspaces/FoodVibes ]$ cd ui
(foodvibes-all-in-one) vscode [ /workspaces/FoodVibes/ui ]$ yarn install
➤ YN0065: Yarn will periodically gather anonymous telemetry: https://yarnpkg.com/advanced/telemetry
➤ YN0065: Run yarn config set --home enableTelemetry 0 to disable
```

Start the service (every time that you want to start the service).

```bash
(foodvibes-all-in-one) vscode [ /workspaces/FoodVibes/ui ]$ yarn start

  VITE v5.2.12  ready in 1396 ms

  ➜  Local:   https://localhost:3000/
  ➜  Network: https://10.201.32.190:3000/
  ➜  Network: https://172.18.0.1:3000/
  ➜  Network: https://172.17.0.1:3000/
  ➜  press h + enter to show help

```

The above command should start the browser automatically on port 3000.
