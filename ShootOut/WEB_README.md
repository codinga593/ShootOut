# ShootOut browser build

The browser edition runs the original Pygame single-player game through
WebAssembly. It supports keyboard and mouse input in current desktop browsers.

## Play the packaged build

Start the combined game and multiplayer server from this folder:

```sh
python3 Server_v2.py
```

Then open <http://localhost:8000> and click the page once when prompted to
enable game audio.

Controls:

- `WASD`: move
- Mouse or `Space`: aim and shoot
- `1` / `2`: change weapon
- `R`: reload
- `E`: open a nearby chest
- `F`: collect a nearby power-up
- `Q`: use a medkit
- `Tab`: toggle the minimap
- `L`: restart after defeat
- `Esc`: return to the menu

The upload-ready archive is `build/web.zip`. It can be deployed to any static
web host that serves `index.html`, `favicon.png`, and `shootout.apk` from the
same directory.

## Rebuild

Install the web packager once:

```sh
python3 -m pip install -r requirements-web.txt
```

Then run:

```sh
./build_web.sh
```

The browser menu includes both single-player and WebSocket multiplayer. Share
your computer's LAN address with other players on the same network, for example
`http://192.168.1.20:8000`. Up to eight players can join the same match.
