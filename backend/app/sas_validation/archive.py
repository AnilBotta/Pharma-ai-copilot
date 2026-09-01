"""Pack a validation package into one deterministic ZIP.

DETERMINISM IS NOT TIDINESS HERE

A ZIP that varies between builds of the same package would give the same
package id two different archive hashes, and the archive hash is what a
customer checks their download against. `zipfile` writes the current time into
every entry by default, so two archives of identical files differ within a
second of each other.

So every entry gets a fixed timestamp and fixed external attributes, the files
are written in a fixed order, and compression is deflate at a fixed level. The
same package always produces byte-identical bytes.

The fixed timestamp is 1980-01-01, the earliest the ZIP format can represent.
It is obviously not a real time, which is the point: nobody should read an
entry date as when anything happened. The real generation time is in the
manifest, which is inside the archive and covered by its hash.
"""

from __future__ import annotations

import io
import zipfile

from app.sas_validation.package import ValidationPackage

#: The ZIP epoch. Not a real time and not meant to look like one.
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

#: rw-r--r-- as a ZIP external attribute. Fixed so the archive does not vary
#: with the umask of whatever machine built it.
FIXED_EXTERNAL_ATTR = (0o100644 & 0xFFFF) << 16

#: README first, so a customer opening the archive sees the instructions before
#: the file they are most likely to edit.
FILE_ORDER = (
    "README.md",
    "validate.sas",
    "dataset.csv",
    "model_specification.json",
    "manifest.json",
)


def build_archive(package: ValidationPackage) -> bytes:
    """Deterministic ZIP of every file in the package.

    Raises if the package contains a file this function does not know how to
    order. That is deliberate: silently appending an unknown file in dictionary
    order would make the archive's byte layout depend on a filename, and a
    later rename would change the archive hash of a package whose contents had
    not changed.
    """
    known = {file.name for file in package.files}
    unexpected = known - set(FILE_ORDER)
    if unexpected:
        raise ValueError(
            f"package {package.package_id[:16]} contains files this archive "
            f"builder has no fixed position for: {sorted(unexpected)}. Add "
            "them to FILE_ORDER rather than letting the layout depend on "
            "sort order."
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for name in FILE_ORDER:
            if name not in known:
                continue
            info = zipfile.ZipInfo(filename=name, date_time=FIXED_TIMESTAMP)
            info.external_attr = FIXED_EXTERNAL_ATTR
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, package.file(name).content.encode("utf-8"))

    return buffer.getvalue()


def archive_filename(package: ValidationPackage) -> str:
    """A name that identifies the package without being a path.

    No slashes, no user-supplied text, no extension games - it is built from
    the case id and the package hash, both of which this application generated.
    """
    return f"sas-validation-{package.case_id.lower()}-{package.package_id[:16]}.zip"


__all__ = ["FILE_ORDER", "archive_filename", "build_archive"]
