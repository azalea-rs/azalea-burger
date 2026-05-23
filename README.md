A tool for extracting data from the jar file for the latest Minecraft snapshot.

This is a fork of Burger, which was maintained by TkTech and pokechu22.
This fork exists for use in [Azalea](https://github.com/azalea-rs/azalea)'s
code generator, so features that aren't necessary for that purpose will not be
maintained and may be removed in the future.

Unlike upstream, this fork is not designed to work on old Minecraft versions
(but in some cases it may coincidentally still partially work).

You are encouraged to use azalea-burger in conjunction with
[azalea-pumpkin-extractor](https://github.com/azalea-rs/azalea-pumpkin-extractor)
and the
[vanilla data generator](https://minecraft.wiki/w/Tutorial:Running_the_data_generator).

## The Idea

Burger is made up of _toppings_, which can provide and satisfy simple
dependencies, and which can be run all-together or just a few specifically. Each
topping is then aggregated by `munch.py` into the whole and output as a JSON
dictionary.

## Usage

The simplest way to use Burger is to pass the version as the only argument,
which will download the specified Minecraft client for you. The downloaded jar
will be saved in the working directory, and if it already exists the existing
verison will be used.

    $ uv run munch.py 1.21.5

To download the latest snapshot, the string "latest" can be passed instead.

    $ uv run munch.py latest

Alternatively, you can specify the client jar by passing it as an argument.

    $ uv run munch.py 1.21.5.jar

You can redirect the output from the default `stdout` by passing `-o <path>` or
`--output <path>`.

    $ uv run munch.py latest --output output.json

You can see what toppings are available by passing `-l` or `--list`.

    $ uv run munch.py --list

You can also run specific toppings by passing a comma-delimited list to `-t` or
`--toppings`. If a topping cannot be used because it's missing a dependency, it
will output an error telling you what also needs to be included. Toppings will
generally automatically load their dependencies, however.

    $ uv run munch.py latest --toppings language,stats

The above example would only extract the language information, as well as the
stats and achievements (both part of `stats`).
