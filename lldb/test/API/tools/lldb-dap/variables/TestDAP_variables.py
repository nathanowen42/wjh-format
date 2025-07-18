"""
Test lldb-dap variables request
"""

import os

import lldbdap_testcase
from lldbsuite.test.decorators import *
from lldbsuite.test.lldbtest import *


def make_buffer_verify_dict(start_idx, count, offset=0):
    verify_dict = {}
    for i in range(start_idx, start_idx + count):
        verify_dict["[%i]" % (i)] = {"type": "int", "value": str(i + offset)}
    return verify_dict


class TestDAP_variables(lldbdap_testcase.DAPTestCaseBase):
    def verify_values(self, verify_dict, actual, varref_dict=None, expression=None):
        if "equals" in verify_dict:
            verify = verify_dict["equals"]
            for key in verify:
                verify_value = verify[key]
                actual_value = actual[key]
                self.assertEqual(
                    verify_value,
                    actual_value,
                    '"%s" keys don\'t match (%s != %s) from:\n%s'
                    % (key, actual_value, verify_value, actual),
                )
        if "startswith" in verify_dict:
            verify = verify_dict["startswith"]
            for key in verify:
                verify_value = verify[key]
                actual_value = actual[key]
                startswith = actual_value.startswith(verify_value)
                self.assertTrue(
                    startswith,
                    ('"%s" value "%s" doesn\'t start with "%s")')
                    % (key, actual_value, verify_value),
                )
        if "matches" in verify_dict:
            verify = verify_dict["matches"]
            for key in verify:
                verify_value = verify[key]
                actual_value = actual[key]
                self.assertRegex(
                    actual_value,
                    verify_value,
                    ('"%s" value "%s" doesn\'t match pattern "%s")')
                    % (key, actual_value, verify_value),
                )
        if "contains" in verify_dict:
            verify = verify_dict["contains"]
            for key in verify:
                contains_array = verify[key]
                actual_value = actual[key]
                self.assertIsInstance(contains_array, list)
                for verify_value in contains_array:
                    self.assertIn(verify_value, actual_value)
        if "missing" in verify_dict:
            missing = verify_dict["missing"]
            for key in missing:
                self.assertNotIn(
                    key, actual, 'key "%s" is not expected in %s' % (key, actual)
                )
        hasVariablesReference = "variablesReference" in actual
        varRef = None
        if hasVariablesReference:
            # Remember variable references in case we want to test further
            # by using the evaluate name.
            varRef = actual["variablesReference"]
            if varRef != 0 and varref_dict is not None:
                if expression is None:
                    evaluateName = actual["evaluateName"]
                else:
                    evaluateName = expression
                varref_dict[evaluateName] = varRef
        if (
            "hasVariablesReference" in verify_dict
            and verify_dict["hasVariablesReference"]
        ):
            self.assertTrue(hasVariablesReference, "verify variable reference")
        if "children" in verify_dict:
            self.assertTrue(
                hasVariablesReference and varRef is not None and varRef != 0,
                ("children verify values specified for " "variable without children"),
            )

            response = self.dap_server.request_variables(varRef)
            self.verify_variables(
                verify_dict["children"], response["body"]["variables"], varref_dict
            )

    def verify_variables(self, verify_dict, variables, varref_dict=None):
        for variable in variables:
            name = variable["name"]
            if not name.startswith("std::"):
                self.assertIn(
                    name, verify_dict, 'variable "%s" in verify dictionary' % (name)
                )
                self.verify_values(verify_dict[name], variable, varref_dict)

    def darwin_dwarf_missing_obj(self, initCommands):
        self.build(debug_info="dwarf")
        program = self.getBuildArtifact("a.out")
        main_obj = self.getBuildArtifact("main.o")
        self.assertTrue(os.path.exists(main_obj))
        # Delete the main.o file that contains the debug info so we force an
        # error when we run to main and try to get variables
        os.unlink(main_obj)

        self.create_debug_adapter()
        self.assertTrue(os.path.exists(program), "executable must exist")

        self.launch(program, initCommands=initCommands)

        functions = ["main"]
        breakpoint_ids = self.set_function_breakpoints(functions)
        self.assertEqual(len(breakpoint_ids), len(functions), "expect one breakpoint")
        self.continue_to_breakpoints(breakpoint_ids)

        locals = self.dap_server.get_local_variables()

        verify_locals = {
            "<error>": {
                "equals": {"type": "const char *"},
                "contains": {
                    "value": [
                        "debug map object file ",
                        'main.o" containing debug info does not exist, debug info will not be loaded',
                    ]
                },
            },
        }
        varref_dict = {}
        self.verify_variables(verify_locals, locals, varref_dict)

    def do_test_scopes_variables_setVariable_evaluate(
        self, enableAutoVariableSummaries: bool
    ):
        """
        Tests the "scopes", "variables", "setVariable", and "evaluate"
        packets.
        """
        program = self.getBuildArtifact("a.out")
        self.build_and_launch(
            program, enableAutoVariableSummaries=enableAutoVariableSummaries
        )
        source = "main.cpp"
        breakpoint1_line = line_number(source, "// breakpoint 1")
        lines = [breakpoint1_line]
        # Set breakpoint in the thread function so we can step the threads
        breakpoint_ids = self.set_source_breakpoints(source, lines)
        self.assertEqual(
            len(breakpoint_ids), len(lines), "expect correct number of breakpoints"
        )
        self.continue_to_breakpoints(breakpoint_ids)
        locals = self.dap_server.get_local_variables()
        globals = self.dap_server.get_global_variables()
        buffer_children = make_buffer_verify_dict(0, 16)
        verify_locals = {
            "argc": {
                "equals": {
                    "type": "int",
                    "value": "1",
                },
            },
            "argv": {
                "equals": {"type": "const char **"},
                "startswith": {"value": "0x"},
                "hasVariablesReference": True,
            },
            "pt": {
                "equals": {
                    "type": "PointType",
                },
                "hasVariablesReference": True,
                "children": {
                    "x": {"equals": {"type": "int", "value": "11"}},
                    "y": {"equals": {"type": "int", "value": "22"}},
                    "buffer": {"children": buffer_children},
                },
            },
            "x": {"equals": {"type": "int"}},
        }

        verify_globals = {
            "s_local": {"equals": {"type": "float", "value": "2.25"}},
        }
        s_global = {"equals": {"type": "int", "value": "234"}}
        g_global = {"equals": {"type": "int", "value": "123"}}
        if lldbplatformutil.getHostPlatform() == "windows":
            verify_globals["::s_global"] = s_global
            verify_globals["g_global"] = g_global
        else:
            verify_globals["s_global"] = s_global
            verify_globals["::g_global"] = g_global

        varref_dict = {}
        self.verify_variables(verify_locals, locals, varref_dict)
        self.verify_variables(verify_globals, globals, varref_dict)
        # pprint.PrettyPrinter(indent=4).pprint(varref_dict)
        # We need to test the functionality of the "variables" request as it
        # has optional parameters like "start" and "count" to limit the number
        # of variables that are fetched
        varRef = varref_dict["pt.buffer"]
        response = self.dap_server.request_variables(varRef)
        self.verify_variables(buffer_children, response["body"]["variables"])
        # Verify setting start=0 in the arguments still gets all children
        response = self.dap_server.request_variables(varRef, start=0)
        self.verify_variables(buffer_children, response["body"]["variables"])
        # Verify setting count=0 in the arguments still gets all children.
        # If count is zero, it means to get all children.
        response = self.dap_server.request_variables(varRef, count=0)
        self.verify_variables(buffer_children, response["body"]["variables"])
        # Verify setting count to a value that is too large in the arguments
        # still gets all children, and no more
        response = self.dap_server.request_variables(varRef, count=1000)
        self.verify_variables(buffer_children, response["body"]["variables"])
        # Verify setting the start index and count gets only the children we
        # want
        response = self.dap_server.request_variables(varRef, start=5, count=5)
        self.verify_variables(
            make_buffer_verify_dict(5, 5), response["body"]["variables"]
        )
        # Verify setting the start index to a value that is out of range
        # results in an empty list
        response = self.dap_server.request_variables(varRef, start=32, count=1)
        self.assertEqual(
            len(response["body"]["variables"]),
            0,
            "verify we get no variable back for invalid start",
        )

        # Test evaluate
        expressions = {
            "pt.x": {
                "equals": {"result": "11", "type": "int"},
                "hasVariablesReference": False,
            },
            "pt.buffer[2]": {
                "equals": {"result": "2", "type": "int"},
                "hasVariablesReference": False,
            },
            "pt": {
                "equals": {"type": "PointType"},
                "startswith": {
                    "result": (
                        "{x:11, y:22, buffer:{...}}"
                        if enableAutoVariableSummaries
                        else "PointType @ 0x"
                    )
                },
                "hasVariablesReference": True,
            },
            "pt.buffer": {
                "equals": {"type": "int[16]"},
                "startswith": {
                    "result": (
                        "{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, ...}"
                        if enableAutoVariableSummaries
                        else "int[16] @ 0x"
                    )
                },
                "hasVariablesReference": True,
            },
            "argv": {
                "equals": {"type": "const char **"},
                "startswith": {"result": "0x"},
                "hasVariablesReference": True,
            },
            "argv[0]": {
                "equals": {"type": "const char *"},
                "startswith": {"result": "0x"},
                "hasVariablesReference": True,
            },
            "2+3": {
                "equals": {"result": "5", "type": "int"},
                "hasVariablesReference": False,
            },
        }
        for expression in expressions:
            response = self.dap_server.request_evaluate(expression)
            self.verify_values(expressions[expression], response["body"])

        # Test setting variables
        self.set_local("argc", 123)
        argc = self.get_local_as_int("argc")
        self.assertEqual(argc, 123, "verify argc was set to 123 (123 != %i)" % (argc))

        self.set_local("argv", 0x1234)
        argv = self.get_local_as_int("argv")
        self.assertEqual(
            argv, 0x1234, "verify argv was set to 0x1234 (0x1234 != %#x)" % (argv)
        )

        # Set a variable value whose name is synthetic, like a variable index
        # and verify the value by reading it
        variable_value = 100
        response = self.dap_server.request_setVariable(varRef, "[0]", variable_value)
        # Verify dap sent the correct response
        verify_response = {
            "type": "int",
            "value": str(variable_value),
            "variablesReference": 0,
        }
        for key, value in verify_response.items():
            self.assertEqual(value, response["body"][key])

        response = self.dap_server.request_variables(varRef, start=0, count=1)
        self.verify_variables(
            make_buffer_verify_dict(0, 1, variable_value), response["body"]["variables"]
        )

        # Set a variable value whose name is a real child value, like "pt.x"
        # and verify the value by reading it
        varRef = varref_dict["pt"]
        self.dap_server.request_setVariable(varRef, "x", 111)
        response = self.dap_server.request_variables(varRef, start=0, count=1)
        value = response["body"]["variables"][0]["value"]
        self.assertEqual(
            value, "111", "verify pt.x got set to 111 (111 != %s)" % (value)
        )

        # We check shadowed variables and that a new get_local_variables request
        # gets the right data
        breakpoint2_line = line_number(source, "// breakpoint 2")
        lines = [breakpoint2_line]
        breakpoint_ids = self.set_source_breakpoints(source, lines)
        self.assertEqual(
            len(breakpoint_ids), len(lines), "expect correct number of breakpoints"
        )
        self.continue_to_breakpoints(breakpoint_ids)

        verify_locals["argc"]["equals"]["value"] = "123"
        verify_locals["pt"]["children"]["x"]["equals"]["value"] = "111"
        verify_locals["x @ main.cpp:19"] = {"equals": {"type": "int", "value": "89"}}
        verify_locals["x @ main.cpp:21"] = {"equals": {"type": "int", "value": "42"}}
        verify_locals["x @ main.cpp:23"] = {"equals": {"type": "int", "value": "72"}}

        self.verify_variables(verify_locals, self.dap_server.get_local_variables())

        # Now we verify that we correctly change the name of a variable with and without differentiator suffix
        self.assertFalse(self.dap_server.request_setVariable(1, "x2", 9)["success"])
        self.assertFalse(
            self.dap_server.request_setVariable(1, "x @ main.cpp:0", 9)["success"]
        )

        self.assertTrue(
            self.dap_server.request_setVariable(1, "x @ main.cpp:19", 19)["success"]
        )
        self.assertTrue(
            self.dap_server.request_setVariable(1, "x @ main.cpp:21", 21)["success"]
        )
        self.assertTrue(
            self.dap_server.request_setVariable(1, "x @ main.cpp:23", 23)["success"]
        )

        # The following should have no effect
        self.assertFalse(
            self.dap_server.request_setVariable(1, "x @ main.cpp:23", "invalid")[
                "success"
            ]
        )

        verify_locals["x @ main.cpp:19"]["equals"]["value"] = "19"
        verify_locals["x @ main.cpp:21"]["equals"]["value"] = "21"
        verify_locals["x @ main.cpp:23"]["equals"]["value"] = "23"

        self.verify_variables(verify_locals, self.dap_server.get_local_variables())

        # The plain x variable shold refer to the innermost x
        self.assertTrue(self.dap_server.request_setVariable(1, "x", 22)["success"])
        verify_locals["x @ main.cpp:23"]["equals"]["value"] = "22"

        self.verify_variables(verify_locals, self.dap_server.get_local_variables())

        # In breakpoint 3, there should be no shadowed variables
        breakpoint3_line = line_number(source, "// breakpoint 3")
        lines = [breakpoint3_line]
        breakpoint_ids = self.set_source_breakpoints(source, lines)
        self.assertEqual(
            len(breakpoint_ids), len(lines), "expect correct number of breakpoints"
        )
        self.continue_to_breakpoints(breakpoint_ids)

        locals = self.dap_server.get_local_variables()
        names = [var["name"] for var in locals]
        # The first shadowed x shouldn't have a suffix anymore
        verify_locals["x"] = {"equals": {"type": "int", "value": "19"}}
        self.assertNotIn("x @ main.cpp:19", names)
        self.assertNotIn("x @ main.cpp:21", names)
        self.assertNotIn("x @ main.cpp:23", names)

        self.verify_variables(verify_locals, locals)

    @skipIfWindows
    def test_scopes_variables_setVariable_evaluate(self):
        self.do_test_scopes_variables_setVariable_evaluate(
            enableAutoVariableSummaries=False
        )

    @skipIfWindows
    def test_scopes_variables_setVariable_evaluate_with_descriptive_summaries(self):
        self.do_test_scopes_variables_setVariable_evaluate(
            enableAutoVariableSummaries=True
        )

    @skipIfWindows
    def do_test_scopes_and_evaluate_expansion(self, enableAutoVariableSummaries: bool):
        """
        Tests the evaluated expression expands successfully after "scopes" packets
        and permanent expressions persist.
        """
        program = self.getBuildArtifact("a.out")
        self.build_and_launch(
            program, enableAutoVariableSummaries=enableAutoVariableSummaries
        )
        source = "main.cpp"
        breakpoint1_line = line_number(source, "// breakpoint 1")
        lines = [breakpoint1_line]
        # Set breakpoint in the thread function so we can step the threads
        breakpoint_ids = self.set_source_breakpoints(source, lines)
        self.assertEqual(
            len(breakpoint_ids), len(lines), "expect correct number of breakpoints"
        )
        self.continue_to_breakpoints(breakpoint_ids)

        # Verify locals
        locals = self.dap_server.get_local_variables()
        buffer_children = make_buffer_verify_dict(0, 32)
        verify_locals = {
            "argc": {
                "equals": {"type": "int", "value": "1"},
                "missing": ["indexedVariables"],
            },
            "argv": {
                "equals": {"type": "const char **"},
                "startswith": {"value": "0x"},
                "hasVariablesReference": True,
                "missing": ["indexedVariables"],
            },
            "pt": {
                "equals": {"type": "PointType"},
                "hasVariablesReference": True,
                "missing": ["indexedVariables"],
                "children": {
                    "x": {
                        "equals": {"type": "int", "value": "11"},
                        "missing": ["indexedVariables"],
                    },
                    "y": {
                        "equals": {"type": "int", "value": "22"},
                        "missing": ["indexedVariables"],
                    },
                    "buffer": {
                        "children": buffer_children,
                        "equals": {"indexedVariables": 16},
                    },
                },
            },
            "x": {
                "equals": {"type": "int"},
                "missing": ["indexedVariables"],
            },
        }
        self.verify_variables(verify_locals, locals)

        # Evaluate expandable expression twice: once permanent (from repl)
        # the other temporary (from other UI).
        expandable_expression = {
            "name": "pt",
            "context": {
                "repl": {
                    "equals": {"type": "PointType"},
                    "equals": {
                        "result": """(PointType) $0 = {
  x = 11
  y = 22
  buffer = {
    [0] = 0
    [1] = 1
    [2] = 2
    [3] = 3
    [4] = 4
    [5] = 5
    [6] = 6
    [7] = 7
    [8] = 8
    [9] = 9
    [10] = 10
    [11] = 11
    [12] = 12
    [13] = 13
    [14] = 14
    [15] = 15
  }
}"""
                    },
                    "missing": ["indexedVariables"],
                    "hasVariablesReference": True,
                },
                "hover": {
                    "equals": {"type": "PointType"},
                    "startswith": {
                        "result": (
                            "{x:11, y:22, buffer:{...}}"
                            if enableAutoVariableSummaries
                            else "PointType @ 0x"
                        )
                    },
                    "missing": ["indexedVariables"],
                    "hasVariablesReference": True,
                },
                "watch": {
                    "equals": {"type": "PointType"},
                    "startswith": {
                        "result": (
                            "{x:11, y:22, buffer:{...}}"
                            if enableAutoVariableSummaries
                            else "PointType @ 0x"
                        )
                    },
                    "missing": ["indexedVariables"],
                    "hasVariablesReference": True,
                },
                "variables": {
                    "equals": {"type": "PointType"},
                    "startswith": {
                        "result": (
                            "{x:11, y:22, buffer:{...}}"
                            if enableAutoVariableSummaries
                            else "PointType @ 0x"
                        )
                    },
                    "missing": ["indexedVariables"],
                    "hasVariablesReference": True,
                },
            },
            "children": {
                "x": {"equals": {"type": "int", "value": "11"}},
                "y": {"equals": {"type": "int", "value": "22"}},
                "buffer": {"children": buffer_children},
            },
        }

        # Evaluate from known contexts.
        expr_varref_dict = {}
        for context, verify_dict in expandable_expression["context"].items():
            response = self.dap_server.request_evaluate(
                expandable_expression["name"],
                frameIndex=0,
                threadId=None,
                context=context,
            )
            self.verify_values(
                verify_dict,
                response["body"],
                expr_varref_dict,
                expandable_expression["name"],
            )

        # Evaluate locals again.
        locals = self.dap_server.get_local_variables()
        self.verify_variables(verify_locals, locals)

        # Verify the evaluated expressions before second locals evaluation
        # can be expanded.
        var_ref = expr_varref_dict[expandable_expression["name"]]
        response = self.dap_server.request_variables(var_ref)
        self.verify_variables(
            expandable_expression["children"], response["body"]["variables"]
        )

        # Continue to breakpoint 3, permanent variable should still exist
        # after resume.
        breakpoint3_line = line_number(source, "// breakpoint 3")
        lines = [breakpoint3_line]
        breakpoint_ids = self.set_source_breakpoints(source, lines)
        self.assertEqual(
            len(breakpoint_ids), len(lines), "expect correct number of breakpoints"
        )
        self.continue_to_breakpoints(breakpoint_ids)

        var_ref = expr_varref_dict[expandable_expression["name"]]
        response = self.dap_server.request_variables(var_ref)
        self.verify_variables(
            expandable_expression["children"], response["body"]["variables"]
        )

        # Test that frame scopes have corresponding presentation hints.
        frame_id = self.dap_server.get_stackFrame()["id"]
        scopes = self.dap_server.request_scopes(frame_id)["body"]["scopes"]

        scope_names = [scope["name"] for scope in scopes]
        self.assertIn("Locals", scope_names)
        self.assertIn("Registers", scope_names)

        for scope in scopes:
            if scope["name"] == "Locals":
                self.assertEqual(scope.get("presentationHint"), "locals")
            if scope["name"] == "Registers":
                self.assertEqual(scope.get("presentationHint"), "registers")

    def test_scopes_and_evaluate_expansion(self):
        self.do_test_scopes_and_evaluate_expansion(enableAutoVariableSummaries=False)

    def test_scopes_and_evaluate_expansion_with_descriptive_summaries(self):
        self.do_test_scopes_and_evaluate_expansion(enableAutoVariableSummaries=True)

    def do_test_indexedVariables(self, enableSyntheticChildDebugging: bool):
        """
        Tests that arrays and lldb.SBValue objects that have synthetic child
        providers have "indexedVariables" key/value pairs. This helps the IDE
        not to fetch too many children all at once.
        """
        program = self.getBuildArtifact("a.out")
        self.build_and_launch(
            program, enableSyntheticChildDebugging=enableSyntheticChildDebugging
        )
        source = "main.cpp"
        breakpoint1_line = line_number(source, "// breakpoint 4")
        lines = [breakpoint1_line]
        # Set breakpoint in the thread function so we can step the threads
        breakpoint_ids = self.set_source_breakpoints(source, lines)
        self.assertEqual(
            len(breakpoint_ids), len(lines), "expect correct number of breakpoints"
        )
        self.continue_to_breakpoints(breakpoint_ids)

        # Verify locals
        locals = self.dap_server.get_local_variables()
        # The vector variables might have one additional entry from the fake
        # "[raw]" child.
        raw_child_count = 1 if enableSyntheticChildDebugging else 0
        verify_locals = {
            "small_array": {"equals": {"indexedVariables": 5}},
            "large_array": {"equals": {"indexedVariables": 200}},
            "small_vector": {"equals": {"indexedVariables": 5 + raw_child_count}},
            "large_vector": {"equals": {"indexedVariables": 200 + raw_child_count}},
            "pt": {"missing": ["indexedVariables"]},
        }
        self.verify_variables(verify_locals, locals)

        # We also verify that we produce a "[raw]" fake child with the real
        # SBValue for the synthetic type.
        verify_children = {
            "[0]": {"equals": {"type": "int", "value": "0"}},
            "[1]": {"equals": {"type": "int", "value": "0"}},
            "[2]": {"equals": {"type": "int", "value": "0"}},
            "[3]": {"equals": {"type": "int", "value": "0"}},
            "[4]": {"equals": {"type": "int", "value": "0"}},
        }
        if enableSyntheticChildDebugging:
            verify_children["[raw]"] = ({"contains": {"type": ["vector"]}},)

        children = self.dap_server.request_variables(locals[2]["variablesReference"])[
            "body"
        ]["variables"]
        self.verify_variables(verify_children, children)

    @skipIfWindows
    def test_return_variables(self):
        """
        Test the stepping out of a function with return value show the variable correctly.
        """
        program = self.getBuildArtifact("a.out")
        self.build_and_launch(program)

        return_name = "(Return Value)"
        verify_locals = {
            return_name: {"equals": {"type": "int", "value": "300"}},
            "argc": {},
            "argv": {},
            "pt": {},
            "x": {},
            "return_result": {"equals": {"type": "int"}},
        }

        function_name = "test_return_variable"
        breakpoint_ids = self.set_function_breakpoints([function_name])

        self.assertEqual(len(breakpoint_ids), 1)
        self.continue_to_breakpoints(breakpoint_ids)

        threads = self.dap_server.get_threads()
        for thread in threads:
            if thread.get("reason") == "breakpoint":
                thread_id = thread["id"]

                self.stepOut(threadId=thread_id)

                local_variables = self.dap_server.get_local_variables()
                varref_dict = {}

                # `verify_variable` function only checks if the local variables
                # are in the `verify_dict` passed  this will cause this test to pass
                # even if there is no return value.
                local_variable_names = [
                    variable["name"] for variable in local_variables
                ]
                self.assertIn(
                    return_name,
                    local_variable_names,
                    "return variable is not in local variables",
                )

                self.verify_variables(verify_locals, local_variables, varref_dict)
                break

        self.assertFalse(
            self.dap_server.request_setVariable(1, "(Return Value)", 20)["success"]
        )

    @skipIfWindows
    def test_indexedVariables(self):
        self.do_test_indexedVariables(enableSyntheticChildDebugging=False)

    @skipIfWindows
    def test_indexedVariables_with_raw_child_for_synthetics(self):
        self.do_test_indexedVariables(enableSyntheticChildDebugging=True)

    @skipIfWindows
    @skipIfAsan # FIXME this fails with a non-asan issue on green dragon.
    def test_registers(self):
        """
        Test that registers whose byte size is the size of a pointer on
        the current system get formatted as lldb::eFormatAddressInfo. This
        will show the pointer value followed by a description of the address
        itself. To test this we attempt to find the PC value in the general
        purpose registers, and since we will be stopped in main.cpp, verify
        that the value for the PC starts with a pointer and is followed by
        a description that contains main.cpp.
        """
        program = self.getBuildArtifact("a.out")
        self.build_and_launch(program)
        source = "main.cpp"
        breakpoint1_line = line_number(source, "// breakpoint 1")
        lines = [breakpoint1_line]
        # Set breakpoint in the thread function so we can step the threads
        breakpoint_ids = self.set_source_breakpoints(source, lines)
        self.assertEqual(
            len(breakpoint_ids), len(lines), "expect correct number of breakpoints"
        )
        self.continue_to_breakpoints(breakpoint_ids)

        pc_name = None
        arch = self.getArchitecture()
        if arch == "x86_64":
            pc_name = "rip"
        elif arch == "x86":
            pc_name = "rip"
        elif arch.startswith("arm"):
            pc_name = "pc"

        if pc_name is None:
            return
        # Verify locals
        reg_sets = self.dap_server.get_registers()
        for reg_set in reg_sets:
            if reg_set["name"] == "General Purpose Registers":
                varRef = reg_set["variablesReference"]
                regs = self.dap_server.request_variables(varRef)["body"]["variables"]
                for reg in regs:
                    if reg["name"] == pc_name:
                        value = reg["value"]
                        self.assertTrue(value.startswith("0x"))
                        self.assertIn("a.out`main + ", value)
                        self.assertIn("at main.cpp:", value)

    @no_debug_info_test
    @skipUnlessDarwin
    def test_darwin_dwarf_missing_obj(self):
        """
        Test that if we build a binary with DWARF in .o files and we remove
        the .o file for main.cpp, that we get a variable named "<error>"
        whose value matches the appriopriate error. Errors when getting
        variables are returned in the LLDB API when the user should be
        notified of issues that can easily be solved by rebuilding or
        changing compiler options and are designed to give better feedback
        to the user.
        """
        self.darwin_dwarf_missing_obj(None)

    @no_debug_info_test
    @skipUnlessDarwin
    def test_darwin_dwarf_missing_obj_with_symbol_ondemand_enabled(self):
        """
        Test that if we build a binary with DWARF in .o files and we remove
        the .o file for main.cpp, that we get a variable named "<error>"
        whose value matches the appriopriate error. Test with symbol_ondemand_enabled.
        """
        initCommands = ["settings set symbols.load-on-demand true"]
        self.darwin_dwarf_missing_obj(initCommands)

    @no_debug_info_test
    @skipIfWindows
    def test_value_format(self):
        """
        Test that toggle variables value format between decimal and hexical works.
        """
        program = self.getBuildArtifact("a.out")
        self.build_and_launch(program)
        source = "main.cpp"
        breakpoint1_line = line_number(source, "// breakpoint 1")
        lines = [breakpoint1_line]

        breakpoint_ids = self.set_source_breakpoints(source, lines)
        self.assertEqual(
            len(breakpoint_ids), len(lines), "expect correct number of breakpoints"
        )
        self.continue_to_breakpoints(breakpoint_ids)

        # Verify locals value format decimal
        is_hex = False
        var_pt_x = self.dap_server.get_local_variable_child("pt", "x", is_hex=is_hex)
        self.assertEqual(var_pt_x["value"], "11")
        var_pt_y = self.dap_server.get_local_variable_child("pt", "y", is_hex=is_hex)
        self.assertEqual(var_pt_y["value"], "22")

        # Verify locals value format hexical
        is_hex = True
        var_pt_x = self.dap_server.get_local_variable_child("pt", "x", is_hex=is_hex)
        self.assertEqual(var_pt_x["value"], "0x0000000b")
        var_pt_y = self.dap_server.get_local_variable_child("pt", "y", is_hex=is_hex)
        self.assertEqual(var_pt_y["value"], "0x00000016")

        # Toggle and verify locals value format decimal again
        is_hex = False
        var_pt_x = self.dap_server.get_local_variable_child("pt", "x", is_hex=is_hex)
        self.assertEqual(var_pt_x["value"], "11")
        var_pt_y = self.dap_server.get_local_variable_child("pt", "y", is_hex=is_hex)
        self.assertEqual(var_pt_y["value"], "22")
