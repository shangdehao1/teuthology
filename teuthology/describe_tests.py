# -*- coding: utf-8 -*-

import csv
import json
from prettytable import PrettyTable, FRAME, ALL
import os
import sys
import yaml

from teuthology.exceptions import ParseError
from teuthology.suite import build_matrix, combine_path

def main(args):
    try:
        describe_tests(args)
    except ParseError:
        sys.exit(1)

def describe_tests(args):
    suite_dir = os.path.abspath(args["<suite_dir>"])
    fields = args["--fields"].split(',')
    include_facet = args['--show-facet'] == 'yes'
    output_format = args['--format']

    if args['--combinations']:
        limit = int(args['--limit'])
        filter_in = None
        if args['--filter']:
            filter_in = [f.strip() for f in args['--filter'].split(',')]
        filter_out = None
        if args['--filter-out']:
            filter_out = [f.strip() for f in args['--filter-out'].split(',')]
        subset = None
        if args['--subset']:
            subset = map(int, args['--subset'].split('/'))
        headers, rows = get_combinations(suite_dir, fields, subset,
                                         limit, filter_in,
                                         filter_out, include_facet)
        hrule = ALL
    else:
        headers, rows = describe_suite(suite_dir, fields, include_facet,
                                       output_format)
        hrule = FRAME

    output_results(headers, rows, output_format, hrule)

def output_results(headers, rows, output_format, hrule):
    if output_format == 'json':
        objects = [{k: v for k, v in zip(headers, row) if v}
                   for row in rows]
        print(json.dumps(dict(headers=headers, data=objects)))
    elif output_format == 'csv':
        writer = csv.writer(sys.stdout)
        writer.writerows([headers] + rows)
    else:
        table = PrettyTable(headers)
        table.align = 'l'
        table.vrules = ALL
        table.hrules = hrule
        for row in rows:
            table.add_row(row)
        print(table)

def get_combinations(suite_dir, fields, subset,
                     limit, filter_in, filter_out,
                     include_facet, _isdir=os.path.isdir, _open=open,
                     _isfile=os.path.isfile, _listdir=os.listdir):
    configs = [(combine_path(suite_dir, item[0]), item[1]) for item in
               build_matrix(suite_dir, _isfile, _isdir, _listdir, subset)]

    num_listed = 0
    rows = []

    facet_headers = set()
    dirs = {}
    max_dir_depth = 0

    for _, fragment_paths in configs:
        if limit > 0 and num_listed >= limit:
            break
        if filter_in and not any([f in path for f in filter_in
                                  for path in fragment_paths]):
            continue
        if filter_out and any([f in path for f in filter_out
                               for path in fragment_paths]):
            continue

        fragment_fields = [extract_info(path, fields, _isdir, _open)
                           for path in fragment_paths]

        # merge fields from multiple fragments by joining their values with \n
        metadata = {}
        for fragment_meta in fragment_fields:
            for field, value in fragment_meta.items():
                if value == '':
                    continue
                if field in metadata:
                    metadata[field] += '\n' + str(value)
                else:
                    metadata[field] = str(value)

        if include_facet:
            # map final dir (facet) -> filename without the .yaml suffix
            for path in fragment_paths:
                facet_dir = os.path.dirname(path)
                facet = os.path.basename(facet_dir)
                metadata[facet] = os.path.basename(path)[:-5]
                facet_headers.add(facet)
                facet_dirs = facet_dir.split('/')[:-1]
                for i, dir_ in enumerate(facet_dirs):
                    if i not in dirs:
                        dirs[i] = set()
                    dirs[i].add(dir_)
                    metadata['_dir_' + str(i)] = os.path.basename(dir_)
                    max_dir_depth = max(max_dir_depth, i)

        rows.append(metadata)
        num_listed += 1

    subsuite_headers = []
    if include_facet:
        first_subsuite_depth = max_dir_depth
        for i in range(max_dir_depth):
            if len(dirs[i]) > 1:
                first_subsuite_depth = i
                break

        subsuite_headers = ['subsuite depth ' + str(i)
                            for i in
                            range(0, max_dir_depth - first_subsuite_depth + 1)]

        for row in rows:
            for i in range(first_subsuite_depth, max_dir_depth + 1):
                row[subsuite_headers[i - first_subsuite_depth]] = \
                    row.get('_dir_' + str(i), '')

    headers = subsuite_headers + sorted(facet_headers) + fields
    return headers, sorted([[row.get(field, '') for field in headers]
                            for row in rows])

def describe_suite(suite_dir, fields, include_facet, output_format):
    rows = tree_with_info(suite_dir, fields, include_facet, '', [],
                          output_format=output_format)

    headers = ['path']
    if include_facet:
        headers.append('facet')
    return headers + fields, rows

def extract_info(file_name, fields, _isdir=os.path.isdir, _open=open):
    empty_result = {f: '' for f in fields}
    if _isdir(file_name) or not file_name.endswith('.yaml'):
        return empty_result

    with _open(file_name, 'r') as f:
        parsed = yaml.load(f)

    if not isinstance(parsed, dict):
        return empty_result

    description = parsed.get('description', [{}])
    if not (isinstance(description, list) and
            len(description) == 1 and
            isinstance(description[0], dict)):
        print 'Error in description format in', file_name
        print 'Description must be a list containing exactly one dict.'
        print 'Description is:', description
        raise ParseError()

    return {field: description[0].get(field, '') for field in fields}

def path_relative_to_suites(path):
    try:
        root = os.path.join('ceph-qa-suite', 'suites')
        return path[path.index(root) + len(root):]
    except ValueError:
        return path

def tree_with_info(cur_dir, fields, include_facet, prefix, rows,
                   _listdir=os.listdir, _isdir=os.path.isdir,
                   _open=open, output_format='plain'):
    files = sorted(_listdir(cur_dir))
    has_yamls = any([x.endswith('.yaml') for x in files])
    facet = os.path.basename(cur_dir) if has_yamls else ''
    for i, f in enumerate(files):
        path = os.path.join(cur_dir, f)
        if i == len(files) - 1:
            file_pad = '└── '
            dir_pad = '    '
        else:
            file_pad = '├── '
            dir_pad = '│   '
        info = extract_info(path, fields, _isdir, _open)
        tree_node = prefix + file_pad + f
        if output_format != 'plain':
            tree_node = path_relative_to_suites(path)
        meta = [info[f] for f in fields]
        row = [tree_node]
        if include_facet:
            row.append(facet)
        rows.append(row + meta)
        if _isdir(path):
            tree_with_info(path, fields, include_facet,
                           prefix + dir_pad, rows,
                           _listdir, _isdir, _open, output_format)
    return rows
