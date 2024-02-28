# RoMonitor
<p align="center">
<img alt="GitHub Repo stars" src="https://img.shields.io/github/stars/RoWhoIs/RoMonitor?style=for-the-badge">
<img alt="GitHub forks" src="https://img.shields.io/github/forks/RoWhoIs/RoMonitor?style=for-the-badge">
<img alt="GitHub Issues or Pull Requests" src="https://img.shields.io/github/issues/RoWhoIs/RoMonitor?style=for-the-badge">
</p>
An advanced Roblox item monitoring application to alert you on item updates. 

## Setting it up

1. Create a [Discord Webhook](https://discord.com/safety/using-webhooks-and-embeds#title-3)
2. Clone, or download, this repository
```bash
git clone https://github.com/RoWhoIs/RoMonitor --depth=1 && cd RoMonitor
```
3. Modify `config.json` to include your webhook key and roblosecurity.
4. Run romonitor.py
```bash
python3 romonitor.py -ri 20573078 -t 30 -m 1200
```
<sub>Example command. This will run forever, check the item every 30 seconds, and alert if the item is below 1,200 Robux. </sub>

## Usage

| Operand         | Description                              | Required? |
|:----------------|:-----------------------------------------|:----------|
| -i/--item       | Chooses what item to monitor             | Yes       |
| -M/--mention    | Choose who the bot will mention          | No        |
| -t/--time       | Choose how frequently to scan the item   | No        |
| -m/--minprice   | Choose the minimum price for an alert    | No        |
| -a/--allchanges | Notify of all changes, overrides -m      | No        |
| -r/--runforever | Runs RoMonitor even after a notification | No        |

## Troubleshooting

> Unable to renew token

This issue is caused due to a new Roblox feature, Account Session Protection, which makes it impossible to get tokens required for requests.
To resolve this, head to your [advanced creator settings](https://create.roblox.com/settings/advanced) and disable it.

If you don't want to disable this on your account, create a new account and disable it there.

> Not actually pinging anyone

This is most likely due to you not inputting a proper Discord User ID. To do so, go to the advanced tab in settings, enable Developer Mode, and right click "Copy User ID" on the person you would like pinged.