# Run the bot 24/7 for free (Oracle Cloud Always Free)

The bot then runs on Oracle's server around the clock and sends Telegram picks even with your laptop closed.
Cost: $0 (Always Free). A card is required at sign-up for identity only.

## 1. Create the account (~10 min)
1. Go to https://www.oracle.com/cloud/free/ → **Start for free**. Pick a **home region** close to you
   (e.g. *US East (Ashburn)*). It can't be changed later.
2. Finish sign-up (email, card check). Wait for the "account ready" email.

## 2. Create the server (~5 min)
1. Oracle Cloud console → **☰ → Compute → Instances → Create instance**.
2. **Image:** click *Change image* → **Canonical Ubuntu 24.04**.
3. **Shape:** *Change shape* → **Ampere** → **VM.Standard.A1.Flex**, **2 OCPUs, 12 GB memory**
   (shows "Always Free-eligible").
4. **SSH keys:** choose **Generate a key pair for me** → **Save private key** (a `.key` file lands in Downloads).
5. **Boot volume:** leave the default (about 47 GB).
6. Click **Create**. When it shows **Running**, copy the **Public IP address**.

If you see **"Out of capacity"**: in step 3 try another *Availability domain* (AD-2 / AD-3) or retry later. Free ARM
capacity comes and goes.

## 3. Install the bot (one command, ~15 min + 35 min in the background)
On your Mac, in Terminal (replace the IP and key file name):
```bash
chmod 600 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@YOUR_PUBLIC_IP
```
Type `yes` the first time. Then, on the server:
```bash
curl -fsSL -o setup.sh https://raw.githubusercontent.com/yohancohenai/Traid/claude/tt-elite-quant-pro-6b6pj7/tt-elite-quant-pro/deploy/oracle-setup.sh
bash setup.sh
```
If the download says 404 (private repository), the script can't be fetched this way. Clone with a token instead:
create a **read-only fine-grained GitHub token** for the Traid repo, then run
`git clone -b claude/tt-elite-quant-pro-6b6pj7 https://x-access-token:TOKEN@github.com/yohancohenai/Traid.git && bash Traid/tt-elite-quant-pro/deploy/oracle-setup.sh`.

It asks for your **Telegram bot token** and **chat id**, then builds, starts, and sends a **test alert** to Telegram.
After that it downloads the history and trains the model in the background (~35 min).

## 4. Check it (after ~45 min)
```bash
cd ~/Traid/tt-elite-quant-pro && sudo docker compose exec api python -m ttq.cli status
```
Every line should say **OK**. Picks then arrive in Telegram 24/7, and the server restarts the bot after reboots.

## 5. Stop the Mac copy (avoid double messages)
On your Mac, in the app folder: `docker compose down`. You can still use the screenshot import from the server's web
app (below).

## Web app (optional)
The dashboard isn't exposed to the internet. To open it from your Mac:
```bash
ssh -i ~/Downloads/ssh-key-*.key -L 3000:localhost:3000 ubuntu@YOUR_PUBLIC_IP
```
Then browse to http://localhost:3000 while that window is open. For phone access, install Tailscale (free) on the
server and your phone.

## Updates
```bash
ssh -i ~/Downloads/ssh-key-*.key ubuntu@YOUR_PUBLIC_IP
bash ~/Traid/tt-elite-quant-pro/deploy/update.sh
```
