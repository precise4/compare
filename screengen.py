"""
Copyright (C) 2024 precise4

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

import argparse
import os
import random
from functools import partial
from typing import List, Union

import vapoursynth as vs
from awsmfunc import DynamicTonemap, FrameInfo, ScreenGen, zresize

core = vs.core
import asyncio
from requests_toolbelt.multipart.encoder import MultipartEncoder
import requests
from collections import defaultdict

async def slowpics_comparison(comp_title, img_dir='screens'):
    print('Uploading...')
    post_data = {
        'collectionName': (None, comp_title),
        'hentai': (None, 'false'),
        'optimizeImages': (None, 'false'),
        'public': (None, 'false')
    }

    open_files = []
    image_groups = defaultdict(list)

    # Group images by their numeric prefix
    for image_file in os.listdir(img_dir):
        if image_file.endswith('.png'):
            prefix = image_file[:2]  # Extract the first two characters as the group key
            image_groups[prefix].append(image_file)

    # Ensure each group has the same number of images and is properly indexed
    for i, group in enumerate(sorted(image_groups.keys())):
        for j, image_file in enumerate(sorted(image_groups[group])):
            imgid = os.path.splitext(image_file)[0]
            post_data[f'comparisons[{i}].images[{j}].name'] = (None, imgid)
            f = open(os.path.join(img_dir, image_file), 'rb')
            open_files.append(f)
            post_data[f'comparisons[{i}].images[{j}].file'] = (image_file, f, 'image/png')

    with requests.Session() as client:
        client.get("https://slow.pics/api/comparison")
        files = MultipartEncoder(post_data)
        length = str(files.len)
        headers = {
            "Content-Length": length,
            "Content-Type": files.content_type,
            "X-XSRF-TOKEN": client.cookies.get_dict()["XSRF-TOKEN"]
        }
        response = client.post(
            "https://slow.pics/api/comparison",
            data=files, headers=headers)
        print(f'https://slow.pics/c/{response.text}')

    for f in open_files:
        f.close()


def screengn(args: Union[List, argparse.Namespace]):
    # prefer ffms2, fallback to lsmash for m2ts
    if args.source.endswith(".m2ts"):
        src = core.lsmas.LWLibavSource(args.source)
    else:
        src = core.ffms2.Source(args.source)
        # we don't allow encodes in non-mkv containers anyway
    if args.encode:
        enc = core.ffms2.Source(args.encode)

    if args.web:
        web = core.ffms2.Source(args.web)

    # since encodes are optional we use source length
    num_frames = len(src)
    # these values don't really matter, they're just to cut off intros/credits
    start, end = 1000, num_frames - 10000

    # filter b frames function for frameeval
    def filter_ftype(n, f, clip, frame, frames, ftype="B"):
        if f.props["_PictType"] == ftype:
            frames.append(frame)
        return clip

    # generate random frame numbers, sort, and format for ScreenGen
    # if filter option is on filter out non-b frames in encode
    frames = []
    with open(os.devnull, "wb") as f:
        i = 0
        while len(frames) < args.num:
            frame = random.randint(start, end)
            enc_f = enc[frame]
            enc_f = enc_f.std.FrameEval(partial(filter_ftype, clip=enc_f, frame=frame, frames=frames), enc_f)
            enc_f.output(f)
            i += 1
            if i > args.num * 10:
                raise ValueError("screengn: Encode doesn't seem to contain desired picture type frames.")
    frames = sorted(frames)
    frames = [f"{x}\n" for x in frames]

    # write to file, we might want to re-use these later
    with open("screens.txt", "w") as txt:
        txt.writelines(frames)

    # if an encode exists we have to crop and resize
    if args.encode:
        if src.width != enc.width and src.height != enc.height:
            ref = zresize(enc, preset=src.height)
            crop = [(src.width - ref.width) / 2, (src.height - ref.height) / 2]
            src = src.std.Crop(left=crop[0], right=crop[0], top=crop[1], bottom=crop[1])
            if enc.width / enc.height > 16 / 9:
                width = enc.width
                height = None
            else:
                width = None
                height = enc.height
            src = zresize(src, width=width, height=height)

    # tonemap HDR
    if src.get_frame(0).props["_Primaries"] == 9:
        src = DynamicTonemap(src, src_fmt=False, libplacebo=False, max_chroma=True, adjust_gamma=True)
        if args.encode:
            enc = DynamicTonemap(enc, src_fmt=False, libplacebo=False, max_chroma=True, adjust_gamma=True)

    # add FrameInfo
    src = FrameInfo(src, args.srcname)
    ScreenGen(src, args.dir, "src")
    if args.encode:
        enc = FrameInfo(enc, args.encname)
        ScreenGen(enc, args.dir, "enc")
    if args.web:

        web = FrameInfo(web, args.wname)
        ScreenGen(web, args.dir, "web")

    if args.upload:
      asyncio.run(slowpics_comparison('{} vs {}'.format(args.srcname, args.encname),args.dir))

parser = argparse.ArgumentParser(description="Generate random screenshots using ScreenGen")
parser.add_argument(dest="dir", type=str, help="Output directory")
parser.add_argument("--source", "-s", dest="source", type=str, required=True, help="Source file")
parser.add_argument("--sname", "-sn", dest="srcname", type=str, default="Source", help="Source name")
parser.add_argument("--encode", "-e", dest="encode", default=False, help="Encode file")
parser.add_argument("--ename", "-en", dest="encname", type=str, default="Encode", help="Encode name")
parser.add_argument("--wname", "-wn", dest="webname", type=str, default="Web-dl")
parser.add_argument("--web", "-w", dest="web", default=False)
parser.add_argument("--woff", "-wo", dest="woff", type=int)
parser.add_argument(
    "--num",
    "-n",
    dest="num",
    type=int,
    default=6,
    help="Number of screenshots to generate",
)
parser.add_argument("--upload", '-u', dest="upload", action='store_true', help="Upload the screenshots to slow.pics")
screengn(parser.parse_args())
