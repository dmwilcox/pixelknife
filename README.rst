Pixelknife
==========

:date: 2016-01-14 

Tiny command-line based tool for reviewing, and selecting, photos
through a web based interface.

**Background**

When I wrote pixelknife my home life was conducted from a hacked up Android tablet
with a keyboard.  The problem was I needed a way to select and tag photos for various
operations that did not include Lightroom or other proprietary software.  VNC to a
local X.org was too painful to seriously contemplate for quickly moving through photos,
or anything else.  So pixelknife was written on a tablet in vim, don't judge me.

Benefits
   * run pixelknife on Android or Chrome in a chroot, review photos natively.
   * store ratings and tags *for* a set of photos *with* the photos, in a yaml store.
   * simple rating and tagging means *your friends* can help select your photos (locally of course).

Limitations
   * *Not* designed to run over the wide open Internet.
   * currently does not optimized for minimum HTTP requests or bandwidth usage, it
     was developed for use on localhost and that still shows.
   * supports only JPG and PNG extensions, though is trivially expanded *if* your browser
     supports another kind of image (e.g. webp).  So no raw/.dng files anytime soon.
   * does *not* resize photos, aspect ratio is assumed currently (at 1.5), and does not
     extract JPG thumbnails or other fanciness
   * and currently does *not* track derivative files versus the sources -- if you review
     JPGs looking to make edits on NEFs, pixelknife can not help you with that mapping.

I hope pixelknife can be of use to you -- contributions and fixes are always welcome.


*Requrements*

PyYAML
Also pixelknife is a tad dated, it is uses the pyexiv2 library rather than gobject.
A tarball of pyexiv2 is included in the repo since it is no longer available on pip.


*How It Works*

Symlink pixel_knife.html as index.html into a directory with photos you want to review.
Symlink includes directory as well as 'data'.

::

  # Presuming your current working directory is pixelknife and $PHOTOS is
  # the directory of photos you wish to review.
  ln -s `pwd`/pixel_knife.html $PHOTOS/index.html
  ln -s `pwd`/includes $PHOTOS/data

  PK=`pwd`/pixel_knife.py
  cd $PHOTOS
  python $PK


Now you can open a web browser to:

::

  http://localhost:9000

After reviewing your photos, return to the terminal and stop the server.  Don't
worry it writes out your tags and ratings to a backup file in with the photos.
The name of it by default is 'borgstore.yaml'.

::

  # to end a running program in the terminal issue a ^C or control-c
  # you should see something like
  ...
  Discarding EXIF data for now
  Backed up BorgStore to borgstore.yaml
  Shutting down HTTP server.

TODO: fix printy and add docs here for how to get filenames out of yaml nicely.
