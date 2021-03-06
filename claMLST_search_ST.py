#!/usr/bin/python
# -*- coding: utf-8 -*-

##Copyright (c) 2019 Benoit Valot
##benoit.valot@univ-fcomte.fr
##UMR 6249 Chrono-Environnement, Besançon, France
##Licence GPL

"""Search ST number for an assembly"""

import sys
import os
import argparse
import sqlite3
from Bio import SeqIO
import shutil
import lib.psl as psl
import lib.blat as blat
from lib import __version__

desc = "Search ST number for a strain"
command = argparse.ArgumentParser(prog='claMLST_search_ST.py', \
    description=desc, usage='%(prog)s [options] genome database')
command.add_argument('-i', '--identity', nargs='?', \
    type=float, default=0.9, \
    help='Minimun identity to search gene (default=0.9)')
command.add_argument('-c', '--coverage', nargs='?', \
    type=float, default=0.9, \
    help='Minimun coverage to search gene (default=0.9)')
command.add_argument('-f', '--fasta', \
    type=argparse.FileType("w"), \
    help='Write fasta file with gene allele')
command.add_argument('-p', '--path', nargs='?', \
    type=str, default="/usr/bin", \
    help='Path to BLAT executable (default=/usr/bin)')
command.add_argument('-o', '--output', default=sys.stdout, \
    type=argparse.FileType("w"), \
    help='Write ST search result to (default=stdout)')
command.add_argument('genome', \
    type=argparse.FileType("r"), \
    help='Genome of the strain')
command.add_argument('database', \
    type=argparse.FileType("r"), \
    help='Sqlite database containing MLST sheme')
command.add_argument('-v', '--version', action='version', version="pyMLST: "+__version__)

def create_coregene(cursor, tmpfile):
    ref = int(1)
    cursor.execute('''SELECT DISTINCT gene FROM mlst''')
    all_rows = cursor.fetchall()
    coregenes = []
    for row in all_rows:
        cursor.execute('''SELECT sequence,gene FROM sequences WHERE allele=? and gene=?''', (1,row[0]))
        tmpfile.write('>' + row[0] + "\n" + cursor.fetchone()[0] + "\n")
        coregenes.append(row[0])
    return coregenes

def insert_sequence(cursor, sequence):
    try:
        cursor.execute('''INSERT INTO sequences(sequence) VALUES(?)''', (sequence,))
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        cursor.execute('''SELECT id FROM sequences WHERE sequence=?''', (sequence,))
        return cursor.fetchone()[0]

def read_genome(genome):
    seqs = {}
    for seq in SeqIO.parse(genome, 'fasta'):
        seqs[seq.id] = seq
    return seqs
    
if __name__=='__main__':
    """Performed job on execution script""" 
    args = command.parse_args()    
    database = args.database
    genome = args.genome
    if args.identity<0 or args.identity > 1:
        raise Exception("Identity must be between 0 to 1")
    path = blat.test_blat_exe(args.path)
    tmpfile, tmpout = blat.blat_tmp()
    
    try:
        db = sqlite3.connect(database.name)
        cursor = db.cursor()
        cursor2 = db.cursor()
        
        ##read coregene
        coregenes = create_coregene(cursor, tmpfile)
        tmpfile.close()

        ##BLAT analysis
        sys.stderr.write("Search coregene with BLAT\n")
        genes = blat.run_blat(path, genome, tmpfile, tmpout, args.identity, args.coverage)
        sys.stderr.write("Finish run BLAT, found " + str(len(genes)) + " genes\n")
        
        ##Search sequence MLST
        seqs = read_genome(genome)
        sys.stderr.write("Search allele gene to database\n")
        # print(genes)
        allele = {i:[] for i in coregenes}
        st = {i:set() for i in coregenes}
        for coregene in coregenes:
            if coregene not in genes:
                allele.get(coregene).append("")
                continue
            for gene in genes.get(coregene):
                seq = seqs.get(gene.chro, None)
                if seq is None:
                    raise Exception("Chromosome ID not found " + gene.chro)

                ##verify coverage and correct
                if gene.coverage !=1:
                    gene.searchCorrect()
                    sys.stderr.write("Gene " + gene.geneId() + " fill: added\n")

                    
                ##get sequence
                sequence = str(gene.getSequence(seq)).upper()

                ##verify complet sequence
                if len(sequence) != (gene.end-gene.start):
                    sys.stderr.write("Gene " + gene.geneId() + " removed\n")
                    continue

                ##write fasta file with coregene
                if args.fasta is not None:
                    args.fasta.write(">"+coregene+"\n")
                    args.fasta.write(sequence+"\n")

                ##search allele
                cursor.execute('''SELECT allele FROM sequences WHERE sequence=? and gene=?''', \
                               (sequence, coregene))
                row = cursor.fetchone()
                if row is not None:
                    allele.get(coregene).append(str(row[0]))
                    cursor.execute('''SELECT st FROM mlst WHERE gene=? and allele=?''', \
                               (coregene,row[0]))
                    for row2 in cursor.fetchall():
                        st.get(coregene).add(row2[0])
                else:
                    allele.get(gene.geneId()).append("new")

        ##if only know allele or not found
        ##Seach st
        st_val = []
        if sum([len(i)==1 and i[0] != "new" for i in allele.values()]) == len(allele):
            tmp = None
            for s in st.values():
                if s:
                    if tmp is None:
                        tmp = s
                    else:
                        tmp = tmp.intersection(s)
            st_val = list(tmp)

        ##print result
        coregenes.sort()
        args.output.write("Sample\tST\t"+"\t".join(coregenes)+"\n")
        args.output.write(genome.name + "\t" + ";".join(map(str,st_val)))
        for coregene in coregenes:
            args.output.write("\t" + ";".join(map(str,allele.get(coregene))))
        args.output.write("\n")
        sys.stderr.write("FINISH\n")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        if os.path.exists(tmpfile.name):        
            os.remove(tmpfile.name)
        if os.path.exists(tmpout.name):        
            os.remove(tmpout.name)
