"""Copy generic profile instructions into an explicitly selected local Hermes profile."""
import argparse
import datetime
import os
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-dir', type=Path, required=True)
    args = parser.parse_args()
    root = args.profile_dir.expanduser().resolve(strict=True)
    source = Path(__file__).resolve().parents[1] / 'profile'
    os.umask(0o077)
    for name in ('SOUL.md', 'DEVICE.md'):
        if (root / name).is_symlink():
            raise SystemExit('Refusing a symlinked instruction file')
    backups = root / 'backups'
    if backups.is_symlink():
        raise SystemExit('Refusing symlinked backups')
    backup = backups / ('pocket-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(mode=0o700, parents=True)
    for name in ('SOUL.md', 'DEVICE.md'):
        target = root / name
        if target.exists():
            shutil.copy2(target, backup / name)
        shutil.copyfile(source / name, target)
    print('Profile instructions updated with local backups. No services or API configuration changed.')


if __name__ == '__main__':
    main()
