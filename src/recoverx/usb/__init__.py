"""Windows USB device discovery, read-only physical-disk imaging and helpers.

Everything in this package reads from physical media. Nothing here formats,
initialises, mounts, dismounts, locks or writes to a source disk. The only
file written during acquisition is a NEW image file on a different physical
disk, created with exclusive-create semantics.
"""
