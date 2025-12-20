# SIMAC AI Assistant

<!-- TOC -->
* [SIMAC AI Assistant](#simac-ai-assistant)
  * [Backend Setup on a VPS](#backend-setup-on-a-vps)
    * [Prerequisites](#prerequisites)
    * [Step 1: Get an OpenAI API Key](#step-1-get-an-openai-api-key)
      * [Example `.env` File](#example-env-file)
    * [Step 2: Connect to the VPS](#step-2-connect-to-the-vps)
    * [Step 3: Transfer Your Project and Environment File to the VPS](#step-3-transfer-your-project-and-environment-file-to-the-vps)
    * [Step 4: Update Packages](#step-4-update-packages)
    * [Step 5: Install Docker and Docker Compose](#step-5-install-docker-and-docker-compose)
    * [Step 6: Load the Docker Image](#step-6-load-the-docker-image)
    * [Step 7: Run the Project with Docker Compose](#step-7-run-the-project-with-docker-compose)
  * [Frontend Setup](#frontend-setup)
    * [Step 1: Add CSS Files to the `<head>`](#step-1-add-css-files-to-the-head)
    * [Step 2: Add JavaScript Files to the `<body>`](#step-2-add-javascript-files-to-the-body)
    * [Step 3: Add the Chatbot Component](#step-3-add-the-chatbot-component)
      * [Example HTML File](#example-html-file)
    * [Step 4: Configuring the `baseURL` in `script.min.js`](#step-4-configuring-the-baseurl-in-scriptminjs)
<!-- TOC -->

## Backend Setup on a VPS

### Prerequisites

- A VPS with root or sudo access
- SSH access to the server
- An OpenAI API key
## update torch to support cuda 13
```
pip install --upgrade torch torchvision torchaudio
```
### step 0: setup virtual environment
#### make virtual environment
```
python -m venv .venv
```
#### activate it
```
.venv\scripts\activate.bat
```
#### see packages inside venv
```
pip list
```
#### update pip
```
python.exe -m pip install --upgrade pip
```
#### install requirements.txt
```
pip install -r requirements.txt
```
#### deactivating vevn
```
deactivate
```


### Step 1: Get an OpenAI API Key

1. Visit the [OpenAI Platform](https://platform.openai.com/) and log in to your account.

2. Once logged in, navigate to the **Dashboard** and click on **API keys**.

3. Click on **Create new secret key** to generate a new key.

4. (Optional) You can provide a name for the key to help identify its purpose, then click **Create secret key**.

5. A new API key will be generated. **Copy the key** as it will only be shown once.

6. Paste the copied key in your `.env` file as the value for `OPENAI_API_KEY`.

#### Example `.env` File

Ensure that your `.env` file contains the necessary environment variables like this:

```dotenv
# DOCS & REDOC
DOCUMENTATION=TRUE

# SIMAC
SIMAC_API_KEY=simac-QnrxndWE8iZ3pYLUj36CweOG7nXtkcuVrm9cXSvi0sHArALsY9

# OPENAI
OPENAI_API_KEY=sk-your-generated-key-here

# DATABASE
SQL_DATABASE_URL=postgresql+asyncpg://user:password@db:5432/aidb
```

### Step 2: Connect to the VPS

Open a terminal as an administrator and connect to your VPS using SSH:

```bash
ssh USER@SERVER_IP
```

Replace `USER` with your username and `SERVER_IP` with your server's IP address. You will be asked for a password; type the password and enter your VPS.

### Step 3: Transfer Your Project and Environment File to the VPS

Use `scp` to securely copy your zipped project and the `.env` file to the VPS:

```bash
scp ./.env USER@SERVER_IP:/root/simac-ai-assistant
```

Once all the files have been transferred to the VPS, navigate to the project folder using the following command:

```bash
cd simac-ai-assistant
```

To list all the files in the directory, including hidden files (which typically start with a dot), use:

```bash
ls -a
```

You should see the following files in the directory:

- `.env`
- `docker-compose.yml`
- `simac-ai-1.0.0.tar` (for `fa` version)
- `simac-ai-en-1.0.0.tar` (for `en` version)

Make sure that all these files are present before proceeding to the next step.

### Step 4: Update Packages

Once connected, update the package list:

```bash
sudo apt update
```

### Step 5: Install Docker and Docker Compose

To install Docker and the Docker Compose plugin, run the following commands:

1. Download and install Docker:
    ```bash
    curl -fsSL https://get.docker.com -o get-docker.sh
    ```
    ```bash
    sudo sh get-docker.sh
    ```

2. Install the Docker Compose plugin:
    ```bash
    sudo apt-get install docker-compose-plugin
    ```

Docker and Docker Compose are now ready to use on your VPS.

### Step 6: Load the Docker Image

Once Docker is installed, load your Docker image from a tar file. Run the following command to load the image:

```bash
docker load -i simac-ai-1.0.0.tar  # fa version
docker load -i simac-ai-en-1.0.0.tar  # en version
```

Make sure your Docker image file (`simac-ai-1.0.0.tar`) is located in the correct directory on the server.

### Step 7: Run the Project with Docker Compose

Now that the Docker image is loaded, navigate to the directory where your `docker-compose.yml` file is located and bring up the containers using Docker Compose:

```bash
docker compose up -d
```

This command will run the FastAPI project in detached mode.

## Frontend Setup

To integrate the chatbot into your frontend, follow these steps to include the necessary CSS and JavaScript files.

### Step 1: Add CSS Files to the `<head>`

In your HTML file, add the following two CSS files inside the `<head>` section:

```html
<head>
    <!-- Fonts and Styles for the Chatbot -->
    <link rel="stylesheet" href="static/chatbot/css/fonts.min.css"/>
    <link rel="stylesheet" href="static/chatbot/css/styles.min.css"/>
</head>
```

These files are necessary to style the chatbot, including fonts and layout.

### Step 2: Add JavaScript Files to the `<body>`

Place the following JavaScript files just before the closing `</body>` tag:

```html
<body>
    <!-- Chatbot Functionality Scripts -->
    <script src="static/chatbot/js/chatbot.min.js"></script>
    <script src="static/chatbot/js/script.min.js"></script>
</body>
```

These files contain the logic and functionality for the chatbot.
> **Important Note:**
> - The `fonts.min.css` file **must** be imported **before** `styles.min.css` to ensure proper font loading and styling.
> - The `chatbot.min.js` file **must** be imported **before** `script.min.js` to ensure correct initialization and functionality of the chatbot.

### Step 3: Add the Chatbot Component

To render the chatbot on the page, add the following custom tag in the HTML where you want the chatbot to appear:

```html
<simac-ai-assistant></simac-ai-assistant>
```

This tag will display the SIMAC AI Assistant with the styling and functionality provided by the static files.

#### Example HTML File

Below is a sample HTML file demonstrating how to correctly integrate the chatbot with the necessary CSS and JavaScript files:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Title</title>
    <link rel="stylesheet" href="static/chatbot/css/fonts.min.css"/>
    <link rel="stylesheet" href="static/chatbot/css/styles.min.css"/>
    <!-- SAMPLE STYLE -->
    <style>
        body {
            margin: 0;
            padding: 0;
            background: #dde9f5;
        }
    </style>
</head>
<body>
    <!-- SIMAC CODES HERE -->
    
    <simac-ai-assistant></simac-ai-assistant>
    
    <script src="static/chatbot/js/chatbot.min.js"></script>
    <script src="static/chatbot/js/script.min.js"></script>
</body>
</html>
```

Make sure to adjust the file paths (`static/chatbot/css/` and `static/chatbot/js/`) based on your project structure.

### Step 4: Configuring the `baseURL` in `script.min.js`

In your `script.min.js` file, there is a line that defines the `baseURL`, which specifies the backend server's address that the chatbot will communicate with. By default, this might look something like this:

```javascript
const baseURL = "http://localhost:8000";
```

This URL points to the backend server that serves the API requests made by the chatbot. However, when you deploy your project to a VPS or production server, you need to update this URL to reflect the actual backend server address.

1. **Open `script.min.js`:**  
   Locate the line where `baseURL` is defined, which typically looks like:
   ```javascript
   const baseURL = "http://localhost:8000";
   ```

2. **Update the URL:**  
   Change `http://localhost:8000` to your backend server’s URL. For example, if your FastAPI backend is running on a domain like `https://yourdomain.com`, update the `baseURL` to:
   ```javascript
   const baseURL = "https://yourdomain.com";
   ```
   Now, save the changes and redeploy the `script.min.js` file to your server.
