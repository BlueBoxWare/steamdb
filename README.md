Up-to-date data on (almost[^1]) all Steam games[^2].

- [`data/`](data/): JSON data on the games. A game with `id` can be found in the file `floor(id / 3000)`.

### Lists

- [data/demos](data/demos): IDs of all games with demos
- [data/achievements](data/achievements): IDs of all games with achievements
- [data/cards](data/cards): IDs of all games with trading cards
- [data/categories](data/categories): Data on all store categories
- [data/genres](data/genres): Genre IDs and their description

### Download

- With `git`:

  - **download**: `git clone --depth=1 https://github.com/BlueBoxWare/steamdb.git`
    - This will download the repository to the directory `steamdb` under your current directory.
  - **update**: Go to the downloaded `steamdb` directory and run `git pull`

- [ZIP file](https://github.com/BlueBoxWare/steamdb/archive/refs/heads/main.zip)

[^1]: Games with a region restriction which are not available in Europe are not included.

[^2]: Including DLC, Software, Videos and Hardware.
