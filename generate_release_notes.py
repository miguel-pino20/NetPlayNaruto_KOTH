#!/usr/bin/env python3
"""Genera un borrador Markdown de una release a partir del historial local de Git."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

from release_info import ASSET_NAMES, REPOSITORY, VERSION

ROOT = Path(__file__).resolve().parent
RELEASE_VERSION = re.compile(r"v?\d+\.\d+\.\d+(?:[A-Za-z][\w.-]*|[-+][\w.-]+)?")


def git(root, *arguments):
    return subprocess.run(
        ['git', '-C', str(root), *arguments], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8',
    ).stdout


def markdown(text):
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_\[\]])', r'\\\1', text)


def previous_release(root, version):
    # Prefer version tags reachable from HEAD. Exclude the current release tag.
    tags = [tag for tag in git(root, 'tag', '--merged', 'HEAD').splitlines()
            if RELEASE_VERSION.fullmatch(tag) and tag.removeprefix('v') != version]
    if tags:
        matches = [argument for tag in tags for argument in ('--match', tag)]
        return git(root, 'describe', '--tags', '--abbrev=0', *matches, 'HEAD').strip()
    # This repository also records releases as commits named "0.1.5A".
    for line in git(root, 'log', '--format=%H%x09%s').splitlines():
        commit, subject = line.split('\t', 1)
        if RELEASE_VERSION.fullmatch(subject) and subject.removeprefix('v') != version:
            return commit
    return None


def generate_notes(root, version, repository, assets, since=None,
                   include_uncommitted=False, highlights=()):
    head = git(root, 'rev-parse', 'HEAD').strip()
    base = since if since is not None else previous_release(root, version)
    if base:
        base_commit = git(root, 'rev-parse', '--verify', base + '^{commit}').strip()
        if subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor',
                           base_commit, head], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode:
            raise ValueError('La referencia --since debe ser un antepasado de HEAD.')
        history = base_commit + '..' + head
    else:
        base_commit = None
        history = head
    commits = git(root, 'log', '--reverse', '--no-merges', '--format=%H%x09%s', history)
    lines = [f'# UN5 Netplay {markdown(version)} — Windows y Linux', '',
             '## Cambios', '']
    lines.extend('- ' + markdown(item) for item in highlights)
    count = 0
    for line in commits.splitlines():
        commit, subject = line.split('\t', 1)
        # Version-only commits add no useful description to release notes.
        if RELEASE_VERSION.fullmatch(subject):
            continue
        lines.append(f'- {markdown(subject)} ([{commit[:7]}](https://github.com/{repository}/commit/{commit})).')
        count += 1
    if not count and not highlights:
        lines.append('No hay commits descriptivos nuevos en el intervalo seleccionado.')
    if include_uncommitted:
        paths = git(root, 'diff', '--name-only', '-z', 'HEAD').split('\0')
        paths = [path for path in paths if path]
        if paths:
            lines += ['', '## Cambios locales pendientes de commit', '',
                      'Estos archivos tienen cambios locales; no forman parte del historial publicado.', '']
            lines.extend('- ' + markdown(path) for path in paths)
    lines += ['', '## Descargas', '', '| Plataforma | Archivo |', '| --- | --- |']
    for platform, name in assets.items():
        label = {'linux': 'Linux x86_64', 'windows': 'Windows x64'}.get(platform, platform)
        lines.append(f'| {markdown(label)} | {markdown(name)} |')
    lines += ['', 'Adjunta también el archivo `.sha256` correspondiente a cada paquete.', '',
              'Los paquetes incluyen Python y sus dependencias. PCSX2, BIOS y juegos se configuran por separado.', '',
              '## Antes de jugar', '',
              '- Habilita PINE en PCSX2, slot **28011**.',
              '- Windows: abre PCSX2 manualmente y carga el juego.',
              '- Linux: requiere PCSX2 mediante Flatpak (`net.pcsx2.PCSX2`).',
              '- Los modos ZeroTier requieren ZeroTier instalado y conectado a la red.', '',
              'Las salas D.O.N y Digimon siguen siendo experimentales.', '',
              '## Validación', '',
              'Pendiente de documentar las pruebas realizadas para esta versión. '
              'Este generador no compila ni verifica los paquetes.']
    if base_commit:
        lines += ['', f'[Ver cambios en GitHub](https://github.com/{repository}/compare/{base_commit}...{head})']
    return '\n'.join(lines) + '\n'


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since', help='Tag o commit anterior; por defecto detecta la última release')
    parser.add_argument('--output', type=Path, help='Salida; por defecto dist/RELEASE_NOTES-VERSION.md')
    parser.add_argument('--stdout', action='store_true', help='Mostrar Markdown sin escribir archivos')
    parser.add_argument('--include-uncommitted', action='store_true',
                        help='Listar también archivos versionados con cambios locales')
    parser.add_argument('--highlight', action='append', default=[], metavar='TEXTO',
                        help='Añadir una novedad redactada por ti; se puede repetir')
    parser.add_argument('--force', action='store_true', help='Permitir reemplazar un archivo existente')
    args = parser.parse_args(arguments)
    if args.stdout and args.output:
        parser.error('--stdout y --output no se pueden combinar')
    try:
        notes = generate_notes(ROOT, VERSION, REPOSITORY, ASSET_NAMES, args.since,
                               args.include_uncommitted, args.highlight)
        if args.stdout:
            print(notes, end='')
        else:
            destination = args.output or ROOT / 'dist' / f'RELEASE_NOTES-{VERSION}.md'
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('w' if args.force else 'x', encoding='utf-8') as output:
                output.write(notes)
            print(f'Borrador generado: {destination.resolve()}')
            print('Revisa los cambios y completa la validación antes de publicarlo.')
    except FileExistsError:
        parser.exit(1, 'El archivo ya existe. Usa --force para reemplazarlo o elige otro --output.\n')
    except subprocess.CalledProcessError as error:
        parser.exit(1, f'Error de Git: {error.stderr.strip()}\n')
    except (OSError, ValueError) as error:
        parser.exit(1, f'Error: {error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
