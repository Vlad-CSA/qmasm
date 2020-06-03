###################################
# Output QUBOs in various formats #
# By Scott Pakin <pakin@lanl.gov> #
###################################

import datetime
import json
import math
import os
import qmasm
import random
import re
import sys
try:
    from dwave_sapi2.util import linear_index_to_chimera
except ImportError:
    from .fake_dwave import *

def open_output_file(oname):
    "Open a file or standard output."
    if oname == "<stdout>":
        outfile = sys.stdout
    else:
        try:
            outfile = open(oname, "w")
        except IOError:
            qmasm.abend('Failed to open %s for output' % oname)
    return outfile

def coupler_number(M, N, L, q1, q2):
    "Map a pair of qubits to a coupler number a la the dw command."
    qmin = min(q1, q2)
    qmax = max(q1, q2)
    [[imin, jmin, umin, kmin], [imax, jmax, umax, kmax]] = linear_index_to_chimera([qmin, qmax], M, N, L)
    cell_links = L*L
    if imin == imax and jmin == jmax and umin != umax:
        # Same unit cell
        return cell_links*(imin*M + jmin) + kmin*L + kmax
    total_intra = cell_links*M*N
    if imin == imax and jmin + 1 == jmax and umin == umax and kmin == kmax:
        # Horizontal (same cell row)
        return total_intra + L*(imin*(M - 1) + jmin) + kmin
    total_horiz = (M - 1)*N*L
    if imin + 1 == imax and jmin == jmax and umin == umax and kmin == kmax:
        # Vertical (same cell column)
        return total_intra + total_horiz + L*(imin*M + jmin) + kmin
    raise IndexError("No coupler exists between Q%04d and Q%04d" % (q1, q2))

def output_qubist(outfile, as_qubo, problem):
    "Output weights and strengths in Qubist format, either Ising or QUBO."
    if as_qubo and not problem.qubo:
        qprob = problem.convert_to_qubo()
        output_weights, output_strengths = qprob.weights, qprob.strengths
    elif not as_qubo and problem.qubo:
        iprob = problem.convert_to_ising()
        output_weights, output_strengths = iprob.weights, iprob.strengths
    else:
        output_weights = problem.weights
        output_strengths = problem.strengths
    data = []
    for q, wt in sorted(output_weights.items()):
        if wt != 0.0:
            data.append("%d %d %.10g" % (q, q, wt))
    for sp, str in sorted(output_strengths.items()):
        if str != 0.0:
            data.append("%d %d %.10g" % (sp[0], sp[1], str))

    # Output the header and data in Qubist format.
    try:
        num_qubits = qmasm.solver.properties["num_qubits"]
    except KeyError:
        # The Ising heuristic solver is an example of a solver that lacks a
        # fixed hardware representation.  We therefore assert that the number
        # of qubits is exactly the number of qubits we require.
        num_qubits = len(output_weights)
    outfile.write("%d %d\n" % (num_qubits, len(data)))
    for d in data:
        outfile.write("%s\n" % d)

def output_dw(outfile, problem):
    "Output weights and strengths in dw format."
    if not problem.qubo:
        qprob = problem.convert_to_qubo()
        output_weights, output_strengths = qprob.weights, qprob.strengths
    else:
        output_weights = problem.weights
        output_strengths = problem.strengths
    try:
        L, M, N = qmasm.chimera_topology(qmasm.solver)
    except qmasm.NonChimera:
        qmasm.abend("dw output is supported only for Chimera-graph topologies")
    wdata = []
    for q in range(len(output_weights)):
        if output_weights[q] != 0.0:
            wdata.append("Q%0d <== %.25g" % (q, output_weights[q]))
    wdata.sort()
    sdata = []
    for sp, str in output_strengths.items():
        if str != 0.0:
            try:
                coupler = coupler_number(M, N, L, sp[0], sp[1])
            except IndexError:
                qmasm.abend("dw output is supported only for Chimera-graph topologies")
            sdata.append("C%04d <== %.25g" % (coupler, str))
    sdata.sort()
    outfile.write("\n".join(wdata + sdata) + "\n")

def output_qbsolv(outfile, problem):
    "Output weights and strengths in qbsolv format."
    # Determine the list of nonzero weights and strengths.
    if not problem.qubo:
        qprob = problem.convert_to_qubo()
        output_weights, output_strengths = qprob.weights, qprob.strengths
    else:
        output_weights = problem.weights
        output_strengths = problem.strengths
    max_node = max(list(output_weights.keys()) + [max(qs) for qs in output_strengths.keys()])
    num_nonzero_weights = len([q for q, wt in output_weights.items() if wt != 0.0])
    num_nonzero_strengths = len([qs for qs, wt in output_strengths.items() if wt != 0.0])

    # Assign dummy qubit numbers to qubits whose value is known a priori.
    n_known = len(problem.known_values)
    extra_nodes = dict(zip(sorted(problem.known_values.keys()),
                           range(max_node + 1, max_node + 1 + n_known)))
    max_node += n_known
    num_nonzero_weights += n_known
    output_weights.update({num: problem.known_values[sym]*qmasm.pin_weight
                           for sym, num in extra_nodes.items()})
    sym2num = dict(qmasm.sym_map.symbol_number_items())
    sym2num.update(extra_nodes)

    # Output a name-to-number map as header comments.
    key_width = 0
    val_width = 0
    items = []
    for s, n in sym2num.items():
        if len(s) > key_width:
            key_width = len(s)

        # Map logical to physical if possible.
        try:
            nstr = " ".join([str(n) for n in sorted(problem.embedding[n])])
        except AttributeError:
            nstr = str(n)
        if len(nstr) > val_width:
            val_width = len(nstr)
        items.append((s, nstr))
    items.sort()
    for s, nstr in items:
        outfile.write("c %-*s --> %-*s\n" % (key_width, s, val_width, nstr))

    # Output all nonzero weights and strengths.
    outfile.write("p qubo 0 %d %d %d\n" % (max_node + 1, num_nonzero_weights, num_nonzero_strengths))
    for q, wt in sorted(output_weights.items()):
        if wt != 0.0:
            outfile.write("%d %d %.10g\n" % (q, q, wt))
    for qs, wt in sorted(output_strengths.items()):
        if wt != 0.0:
            outfile.write("%d %d %.10g\n" % (qs[0], qs[1], wt))

def output_qmasm(outfile):
    "Output weights and strengths as a flattened QMASM source file."
    for p in qmasm.program:
        outfile.write("%s\n" % p.as_str())

# quote was adapted from Python 3's shlex module because the quote method isn't
# included in Python 2's shlex.
_find_unsafe = re.compile(r'[^\w@%+=:,./-]').search
def quote(s):
    """Return a shell-escaped version of the string *s*."""
    if not s:
        return "''"
    if _find_unsafe(s) is None:
        return s

    # Use single quotes, and put single quotes into double quotes
    # the string $'b is then quoted as '$'"'"'b'.
    return "'" + s.replace("'", "'\"'\"'") + "'"

def output_minizinc(outfile, problem, energy=None):
    "Output weights and strengths as a MiniZinc constraint problem."
    # Write some header information.
    outfile.write("""% Use MiniZinc to minimize a given Hamiltonian.
%
% Producer:     QMASM (https://github.com/lanl/qmasm/)
% Author:       Scott Pakin (pakin@lanl.gov)
""")
    outfile.write("%% Command line: %s\n\n" % " ".join([quote(a) for a in sys.argv]))

    # The model is easier to express as a QUBO so convert to that format.
    if problem.qubo:
        qprob = problem
    else:
        qprob = problem.convert_to_qubo()

    # Map each qubit to one or more symbols.
    num2syms = {}
    for s, n in qmasm.sym_map.symbol_number_items():
        try:
            # Physical problem
            for pn in qprob.embedding[n]:
                try:
                    num2syms[pn].append(s)
                except KeyError:
                    num2syms[pn] = [s]
        except AttributeError:
            # Logical problem
            try:
                num2syms[n].append(s)
            except KeyError:
                num2syms[n] = [s]
    for n in num2syms.keys():
        num2syms[n].sort(key=lambda s: ("$" in s, s))

    # Find the character width of the longest list of symbol names.
    max_sym_name_len = max([len(repr(ss)) - 1 for ss in num2syms.values()] + [7])

    # Output all QMASM variables as MiniZinc variables.
    qubits_used = set(qprob.weights.keys())
    qubits_used.update([qs[0] for qs in qprob.strengths.keys()])
    qubits_used.update([qs[1] for qs in qprob.strengths.keys()])
    for q in sorted(qubits_used):
        outfile.write("var 0..1: q%d;  %% %s\n" % (q, " ".join(num2syms[q])))
    outfile.write("\n")

    # Define variables representing products of QMASM variables.  Constrain the
    # product variables to be the products.
    outfile.write("% Define p_X_Y variables and constrain them to be the product of qX and qY.\n")
    for q0, q1 in sorted(qprob.strengths.keys()):
        pstr = "p_%d_%d" % (q0, q1)
        outfile.write("var 0..1: %s;\n" % pstr)
        outfile.write("constraint %s >= q%d + q%d - 1;\n" % (pstr, q0, q1))
        outfile.write("constraint %s <= q%d;\n" % (pstr, q0))
        outfile.write("constraint %s <= q%d;\n" % (pstr, q1))
    outfile.write("\n")

    # Express energy as one, big Hamiltonian.
    scale_to_int = lambda f: int(round(10000.0*f))
    outfile.write("var int: energy =\n")
    weight_terms = ["%8d * q%d" % (scale_to_int(wt), q) for q, wt in sorted(qprob.weights.items())]
    strength_terms = ["%8d * p_%d_%d" % (scale_to_int(s), qs[0], qs[1]) for qs, s in sorted(qprob.strengths.items())]
    all_terms = weight_terms + strength_terms
    outfile.write("  %s;\n" % " +\n  ".join(all_terms))

    # Because we can't both minimize and enumerate all solutions, we normally
    # do only the former with instructions for the user on how to switch to the
    # latter.  However, if an energy was specified, comment out the
    # minimization step and uncomment the enumeration step.
    outfile.write("\n")
    outfile.write("% First pass: Compute the minimum energy.\n")
    if energy == None:
        outfile.write("solve minimize energy;\n")
    else:
        outfile.write("% solve minimize energy;\n")
    outfile.write("""
%% Second pass: Find all minimum-energy solutions.
%%
%% Once you've solved for minimum energy, comment out the "solve minimize
%% energy" line, plug the minimal energy value into the following line,
%% uncomment it and the "solve satisfy" line, and re-run MiniZinc, requesting
%% all solutions this time.  The catch is that you need to use the raw
%% energy value so be sure to modify the output block to show(energy)
%% instead of show(energy/%.10g + %.10g).
""" % (qmasm.minizinc_scale_factor, qprob.offset))
    if energy == None:
        outfile.write("%constraint energy = -12345;\n")
        outfile.write("%solve satisfy;\n\n")
    else:
        outfile.write("constraint energy = %d;\n" % energy)
        outfile.write("solve satisfy;\n\n")

    # Output code to show the results symbolically.  We output in the same
    # format as QMASM normally does.  Unfortunately, I don't know how to get
    # MiniZinc to output the current solution number explicitly so I had to
    # hard-wire "Solution #1".
    outfile.write("output [\n")
    outfile.write('  "Solution #1 (energy = ", show(energy/%.10g + %.10g), ", tally = 1)\\n\\n",\n' % (qmasm.minizinc_scale_factor, qprob.offset))
    outfile.write('  "    %-*s  Spin  Boolean\\n",\n' % (max_sym_name_len, "Name(s)"))
    outfile.write('  "    %s  ----  -------\\n",\n' % ("-" * max_sym_name_len))
    outlist = []
    for n, ss in num2syms.items():
        if ss == []:
            continue
        syms = " ".join(ss)
        line = ""
        line += '"    %-*s  ", ' % (max_sym_name_len, syms)
        if problem.qubo:
            line += 'show_int(4, q%d), ' % n
        else:
            line += 'show_int(4, 2*q%d - 1), ' % n
        line += '"  ", if show(q%d) == "1" then "True" else "False" endif, ' % n
        line += '"\\n"'
        outlist.append(line)
    outlist.sort()
    outfile.write("  %s\n];\n" % ",\n  ".join(outlist))

def output_bqpjson(outfile, as_qubo, problem):
    "Output weights and strengths in bqpjson format, either Ising or QUBO."
    # Prepare the "easy" fields.
    bqp = {}
    bqp["version"] = "1.0.0"
    bqp["id"] = random.randint(2**20, 2**60)
    bqp["scale"] = 1.0
    bqp["offset"] = 0.0
    if as_qubo:
        bqp["variable_domain"] = "boolean"
    else:
        bqp["variable_domain"] = "spin"

    # Prepare the list of all variables.
    var_ids = set(problem.weights.keys())
    for q1, q2 in problem.strengths.keys():
        var_ids.add(q1)
        var_ids.add(q2)
    bqp["variable_ids"] = sorted(var_ids)

    # Prepare the linear terms.
    lin_terms = []
    for q, wt in sorted(problem.weights.items()):
        lin_terms.append({
            "id": q,
            "coeff": wt})
    bqp["linear_terms"] = lin_terms

    # Prepare the quadratic terms.
    quad_terms = []
    strengths = qmasm.canonicalize_strengths(problem.strengths)
    for (q1, q2), wt in sorted(strengths.items()):
        quad_terms.append({
            "id_tail": q1,
            "id_head": q2,
            "coeff": wt})
    bqp["quadratic_terms"] = quad_terms

    # Prepare some metadata.
    metadata = {}
    if as_qubo:
        metadata["description"] = "QUBO problem compiled by QMASM (https://github.com/lanl/qmasm)"
    else:
        metadata["description"] = "Ising problem compiled by QMASM (https://github.com/lanl/qmasm)"
    metadata["command_line"] = qmasm.get_command_line()
    metadata["generated"] = datetime.datetime.utcnow().isoformat()
    if hasattr(problem, "embedding"):
        # Physical problem
        def attempt_assign(key, func):
            "Try assigning a key, but don't complain if we can't."
            try:
                metadata[key] = func()
            except KeyError:
                pass
        attempt_assign("dw_url", lambda: os.environ["DW_INTERNAL__HTTPLINK"])
        attempt_assign("dw_solver_name", lambda: qmasm.solver_name)
        props = qmasm.solver.properties
        attempt_assign("dw_chip_id", lambda: props["chip_id"])
        L, M, N = qmasm.chimera_topology(qmasm.solver)
        metadata["chimera_cell_size"] = L*2
        metadata["chimera_degree"] = max(M, N)
        metadata["equivalent_ids"] = sorted(problem.chains)
        metadata["variable_names"] = {s: problem.embedding[n]
                                      for s, n in qmasm.sym_map.symbol_number_items()}
    else:
        metadata["variable_names"] = {s: [n]
                                      for s, n in qmasm.sym_map.symbol_number_items()}
    bqp["metadata"] = metadata

    # Output the problem in JSON format.
    outfile.write(json.dumps(bqp, indent=2, sort_keys=True) + "\n")

def write_output(problem, oname, oformat, as_qubo):
    "Write an output file in one of a variety of formats."

    # Open the output file.
    outfile = open_output_file(oname)

    # Output the weights and strengths in the specified format.
    if oformat == "qubist":
        output_qubist(outfile, as_qubo, problem)
    elif oformat == "dw":
        output_dw(outfile, problem)
    elif oformat == "qbsolv":
        output_qbsolv(outfile, problem)
    elif oformat == "qmasm":
        output_qmasm(outfile)
    elif oformat == "minizinc":
        output_minizinc(outfile, problem)
    elif oformat == "bqpjson":
        output_bqpjson(outfile, as_qubo, problem)

    # Close the output file.
    if oname != "<stdout>":
        outfile.close()

def output_energy_tallies(physical_ising, answer, full_output):
    # Construct a histogram of energy levels.
    energies = answer["energies"]
    try:
        tallies = answer["num_occurrences"]
    except KeyError:
        tallies = [1] * len(energies)
    new_energy_tallies = {}
    for i in range(len(energies)):
        e = float(energies[i])
        t = int(tallies[i])
        try:
            new_energy_tallies[e] += t
        except KeyError:
            new_energy_tallies[e] = t
    new_energies = sorted(new_energy_tallies.keys())

    # Adjust all of the energies based on the embedding.
    adjust_energy = lambda e: (e + physical_ising.simple_offset + physical_ising.offset)/physical_ising.range_scale
    adj_energies = [adjust_energy(e) for e in new_energies]
    adj_energy_tallies = {adjust_energy(e): t for e, t in new_energy_tallies.items()}

    # If the caller requested full output, generate a complete energy
    # histogram.
    if full_output:
        sys.stderr.write("Energy histogram:\n\n")
        sys.stderr.write("    Raw energy   Adj. energy  Tally\n")
        sys.stderr.write("    -----------  -----------  ------\n")
        for e in new_energies:
            sys.stderr.write("    %11.4f  %11.4f  %6d\n" % (e, adjust_energy(e), new_energy_tallies[e]))
        sys.stderr.write("\n")

    # Compute some descriptive statistics of the raw energy values.
    e_median = qmasm.weighted_median(new_energy_tallies)
    e_mad = qmasm.weighted_mad(new_energy_tallies, e_median)
    e_mean, e_stdev = qmasm.weighted_mean_stdev(new_energy_tallies)

    # Do the same for the adjusted energy values.
    e_median_adj = qmasm.weighted_median(adj_energy_tallies)
    e_mad_adj = qmasm.weighted_mad(adj_energy_tallies, e_median_adj)
    e_mean_adj, e_stdev_adj = qmasm.weighted_mean_stdev(adj_energy_tallies)

    # Output energy statistics.
    last_idx = len(new_energies) - 1
    sys.stderr.write("Energy statistics:\n\n")
    sys.stderr.write("    Statistic  Raw value                Adj. value\n")
    sys.stderr.write("    ---------  -----------------------  -----------------------\n")
    sys.stderr.write("    Minimum    %11.4f              %11.4f\n" % (new_energies[0], adj_energies[0]))
    sys.stderr.write("    Median     %11.4f +/- %-7.4f  %11.4f +/- %-7.4f\n" % (e_median, e_mad, e_median_adj, e_mad_adj))
    sys.stderr.write("    Mean       %11.4f +/- %-7.4f  %11.4f +/- %-7.4f\n" % (e_mean, e_stdev, e_mean_adj, e_stdev_adj))
    sys.stderr.write("    Maximum    %11.4f              %11.4f\n" % (new_energies[last_idx], adj_energies[last_idx]))
    sys.stderr.write("\n")

def _numeric_solution(soln):
    "Convert single- and multi-bit values to numbers."
    # Map each name to a number and to the number of bits required.
    idx_re = re.compile(r'^([^\[\]]+)\[(\d+)\]$')
    name2num = {}
    name2nbits = {}
    for q in range(len(soln.spins)):
        names = soln.names[q]
        spin = soln.spins[q]
        if spin == 3:
            continue
        for nm in names.split():
            # Parse the name into a prefix and array index.
            match = idx_re.search(nm)
            if match == None:
                # No array index: Treat as a 1-bit number.
                name2num[nm] = (spin + 1)//2
                name2nbits[nm] = 1
                continue

            # Integrate the current spin into the overall number.
            array, idx = match.groups()
            b = ((spin + 1)//2) << int(idx)
            try:
                name2num[array] += b
                name2nbits[array] = max(name2nbits[array], int(idx) + 1)
            except KeyError:
                name2num[array] = b
                name2nbits[array] = int(idx) + 1

    # Merge the two maps.
    return {nm: (name2num[nm], name2nbits[nm]) for nm in name2num.keys()}

def _output_solution_int(soln):
    "Helper function for output_solution that outputs integers."
    # Convert each value to a decimal and a binary string.  Along the way, find
    # the width of the longest name and the largest number.
    name2info = _numeric_solution(soln)
    max_sym_name_len = max([len(s) for s in list(name2info.keys()) + ["Name"]])
    max_decimal_len = 7
    max_binary_len = 6
    name2strs = {}
    for name, info in name2info.items():
        bstr = ("{0:0" + str(info[1]) + "b}").format(info[0])
        dstr = str(info[0])
        max_binary_len = max(max_binary_len, len(bstr))
        max_decimal_len = max(max_decimal_len, len(dstr))
        name2strs[name] = (bstr, dstr)

    # Output one name per line.
    print("    %-*s  %-*s  Decimal" % (max_sym_name_len, "Name", max_binary_len, "Binary"))
    print("    %s  %s  %s" % ("-" * max_sym_name_len, "-" * max_binary_len, "-" * max_decimal_len))
    for name, (bstr, dstr) in sorted(name2strs.items()):
        print("    %-*s  %*s  %*s" % (max_sym_name_len, name, max_binary_len, bstr, max_decimal_len, dstr))
    print("")

def _output_solution_bool(soln):
    "Helper function for output_solution that outputs Booleans."
    # Split names that refer to the same qubit.  Along the way, determine
    # the width of the longest name.
    max_sym_name_len = 4   # "Name"
    name_spin = []
    for q in range(len(soln.spins)):
        names = soln.names[q]
        spin = soln.spins[q]
        for nm in names.split():
            name_spin.append((nm, spin))
            if len(nm) > max_sym_name_len:
                max_sym_name_len = len(nm)

    # Output one name per line.
    print("    %-*s  Spin  Boolean" % (max_sym_name_len, "Name"))
    print("    %s  ----  --------" % ("-" * max_sym_name_len))
    bool_str = {-1: "False", +1: "True", 0: "[unused]"}
    output_lines = []
    for name, spin in name_spin:
        if spin == 3:
            # A spin of +3 is too weird to represent an unused qubit so we use 0.
            spin = 0
            spin_str = "   0"
        else:
            spin_str = "%+4d" % spin
        output_lines.append("    %-*s  %s  %-7s" % (max_sym_name_len, name, spin_str, bool_str[spin]))
    output_lines.sort()
    print("\n".join(output_lines) + "\n")

def _output_solution_asserts(soln, verbosity):
    "Helper function for output_solution that outputs assertion results."
    # Do nothing if the program contains no assertions.  Otherwise, output some
    # header text.
    if len(soln.problem.assertions) == 0:
        return
    if verbosity >= 2:
        print("    Assertions made")
        print("    ---------------")
    else:
        print("    Assertions failed")
        print("    -----------------")

    # Output each assertion in turn.
    n_failed = 0
    for (astr, ok) in soln.check_assertions():
        if not ok:
            print("    FAIL: %s" % astr)
            n_failed += 1
        elif verbosity >= 2:
            print("    PASS: %s" % astr)
    if verbosity < 2 and n_failed == 0:
        print("    [none]")
    print("")

def _prettify_energy_func_str(str):
    "Remove zeroes and additions of negative values from a string."
    str = str.replace("+ -", "- ")
    str = str.replace(" - 0.00*P", "")
    str = str.replace(" + 0.00*P", "")
    str = str.replace(" - 0.00*C", "")
    str = str.replace(" + 0.00*C", "")
    str = str.replace("0*", "*")
    return str

def output_solution(solutions, style, verbosity, show_asserts):
    "Output a user-readable solution to the standard output device."
    # Sort the solutions first by energy then by ID.
    soln_key = lambda s: (s.energy, s.id)
    sorted_solns = sorted(solutions.solutions, key=soln_key)

    # Output each solution in turn.
    if len(sorted_solns) == 0:
        print("No valid solutions found.")
        return
    for snum in range(len(sorted_solns)):
        soln = sorted_solns[snum]
        if verbosity >= 2:
            efunc = soln.energy_func()
            str = "Solution #%d (energy = %.2f = %.2f + %.2f*P + %.2f*C, tally = %s):\n" % (snum + 1, soln.energy, efunc[0], efunc[1], efunc[2], soln.tally)
            print(_prettify_energy_func_str(str))
        else:
            print("Solution #%d (energy = %.2f, tally = %s):\n" % (snum + 1, soln.energy, soln.tally))
        if style == "bools":
            _output_solution_bool(soln)
        elif style == "ints":
            _output_solution_int(soln)
        else:
            raise Exception('Output style "%s" not recognized' % style)
        if show_asserts:
            _output_solution_asserts(soln, verbosity)
