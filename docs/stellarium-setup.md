---
title: Stellarium Setup
---

# Connecting Stellarium to Starlock

Starlock doesn't have its own sky chart. It uses [Stellarium](https://stellarium.org/) instead. Stellarium is a free, open-source planetarium app with a beautiful sky chart, thousands of deep-sky objects, and it runs on all platforms. Starlock plugs into Stellarium as a virtual telescope, so you get the best of both: Stellarium for finding and picking targets, Starlock for guiding you there.

This is a one-time setup. Once it's done, Stellarium and Starlock reconnect automatically every time you start them.

## What you'll end up with

- A **live crosshair** on Stellarium's sky chart showing exactly where your telescope is pointing, updating in real time as you push
- **One-click target selection**: click any object in Stellarium and press a keyboard shortcut to send it to Starlock
- **Push direction** in Starlock on your phone or tablet ("left 2°, down 1°") until the target is centered in your eyepiece

## What you'll need

- [Stellarium](https://stellarium.org/) on a laptop or desktop computer
- Starlock running on your [Raspberry Pi](rpi-headless.md)
- The computer on the same network as the Pi: your home Wi-Fi, or the Pi's own hotspot (`Starlock-XXXX`) if you use a [ready-made SD card](rpi-headless.md#b-ready-made-starlock-sd-card)

## Step 1: Enable the Telescope Control plugin

Open Stellarium and press **F2** to open Configuration. Click the **Plugins** tab, then scroll the left list and select **Telescope Control**.

![Enable the Telescope Control plugin in Stellarium](assets/stellarium-telescope-1.jpeg)

Tick **Load at startup**, then **restart Stellarium**. The plugin only activates on startup.

After restarting, go back to **Configuration → Plugins → Telescope Control** and click **configure**.

## Step 2: Create a new telescope

You'll see an empty **Telescopes Controlled** list.

![Empty Telescopes Controlled list](assets/stellarium-telescope-2.jpeg)

Click the **+** button at the bottom to add a new telescope.

## Step 3: Configure it for Starlock

Fill in the dialog like this:

![Add New Telescope dialog configured for Starlock](assets/stellarium-telescope-3.jpeg)

| Setting | What to pick |
|---|---|
| Telescope controlled by | **External software or a remote computer** |
| Name | `Starlock` (or whatever you like) |
| Coordinate system | **J2000 (default)** (don't change this) |
| Start/connect at startup | ✓ tick this |

Scroll down and set:

| Setting | What to enter |
|---|---|
| Host | The Pi's address: `starlock.local`, or its IP address (`192.168.77.1` on the Pi's hotspot) |
| TCP Port | `10001` |

The Pi's IP address is in the link under **Open on your phone**, in the **Connectivity** section of Starlock's Settings (the gear). If `starlock.local` doesn't connect, use the IP address instead.

!!! warning "Leave the coordinate system on J2000"
    Starlock only speaks J2000 coordinates. If you switch this to JNow, the crosshair in Stellarium will be slightly off from where your telescope is actually pointing. If things seem "close but not quite right," this is almost always the reason.

Click **OK**.

## Step 4: Connect

Starlock now appears in the list as **Disconnected**.

![Starlock listed as Disconnected](assets/stellarium-telescope-4.jpeg)

Make sure the Pi is on and Starlock is **running**, then click **Connect**.

## Step 5: Verify

The status should change to **Connected** within a second.

![Starlock connected](assets/stellarium-telescope-5.jpeg)

That's it for setup. Close the dialog. Because you ticked "Start/connect at startup," this will happen automatically from now on. You won't need to open this dialog again.

## Step 6: See the crosshair

Look at Stellarium's sky chart. You'll see a small crosshair labelled **Starlock**. This is where your telescope is pointed right now, updating live.

![Starlock crosshair in Stellarium's sky chart](assets/stellarium-telescope-6.jpeg)

Push your telescope gently and watch the crosshair move in sync. No encoders, no motors. Just the camera seeing the stars and figuring out where it's looking.

## Step 7: Pick a target

Click any object in Stellarium (a star, a nebula, a galaxy, anything). Stellarium highlights it with selection brackets.

![Orion Nebula selected in Stellarium](assets/stellarium-telescope-7.jpeg)

Now press **Cmd+1** (Mac) or **Ctrl+1** (Windows / Linux). This sends the target to Starlock.

## Step 8: Push to it

Look at Starlock on your phone or tablet. It shows the target and how far you need to push:

![Starlock tracking the Great Orion Nebula](assets/starlock.0.2.0-tracking.png)

In this example, the Great Orion Nebula is **3.9°** away: push the telescope **left by 0.4°** and **down by 3.9°** to reach it. The main view shows arrows pointing in the push direction.

As you push, the numbers shrink in real time. When they get close to zero, the target should be visible in your eyepiece. Center it by eye and enjoy the view.

To pick a different target, just click another object in Stellarium and press **Cmd+1** again. To stop tracking, click **Clear Target** in Starlock.

## Troubleshooting

**Can't connect: status stays "Disconnected".**

- Make sure Starlock is running on the Pi *before* you click Connect in Stellarium. Starlock is the server; Stellarium connects to it.
- Make sure the computer and the Pi are on the same network (or the computer is joined to the Pi's hotspot).
- If the Host is `starlock.local`, try the Pi's IP address instead (`192.168.77.1` on the hotspot). Some computers can't resolve `.local` names.
- When you move between networks, the Pi's IP address can change. Update the Host to match.

**The crosshair is in the wrong part of the sky.**

- Check that the coordinate system in the telescope settings is set to **J2000**, not JNow. This is the most common cause.
- Make sure Stellarium's location and time are set correctly for where you are.
- Make sure Starlock has actually solved at least once. If the step indicator in Starlock still says *Sync* rather than *Track*, it doesn't know where it's pointed yet.

**Cmd+1 / Ctrl+1 doesn't seem to do anything.**

- You need to click an object in Stellarium first so it's selected (you'll see brackets around it).
- Make sure the telescope is connected (check the Telescopes dialog).
- On Mac, make sure Stellarium's window has focus before pressing the shortcut.

**Starlock shows the target coordinates but not the name.**

- Stellarium's telescope connection only sends coordinates. Starlock looks up the name through Stellarium's **Remote Control** plugin, but only when Stellarium runs on the same machine as Starlock. With Starlock on a Pi and Stellarium on another computer, targets sent from Stellarium show coordinates without a name. Pushing to them works the same.

## What's next

Now that Stellarium is connected, head to [Using Starlock](using-starlock.md) to learn how to sync, calibrate, and start pushing to targets.
