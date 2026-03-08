"""
Python dynamic call and reflection patterns
"""
import importlib


class DynamicCallExample:
    """Examples of Python dynamic invocation patterns"""
    
    def call_method_by_name(self, obj, method_name: str):
        """Using getattr to call methods dynamically"""
        # getattr with string literal
        method = getattr(obj, "process_payment")
        method()
        
        # getattr with variable
        dynamic_method = getattr(obj, method_name)
        dynamic_method()
        
        # hasattr check
        if hasattr(obj, "validate"):
            getattr(obj, "validate")()
    
    def set_attribute_dynamically(self, obj, attr_name: str, value):
        """Using setattr to modify attributes"""
        # setattr with string literal
        setattr(obj, "status", "active")
        
        # setattr with variable
        setattr(obj, attr_name, value)
    
    def import_module_dynamically(self, module_name: str):
        """Dynamic module imports"""
        # __import__ with string literal
        __import__("json")
        
        # __import__ with variable
        __import__(module_name)
        
        # importlib.import_module with string literal
        importlib.import_module("datetime")
        
        # importlib.import_module with variable
        dynamic_imported = importlib.import_module(module_name)
        
        return dynamic_imported
    
    def access_globals_locals(self):
        """Accessing globals and locals dictionaries"""
        # globals() access
        all_globals = globals()
        func = all_globals.get("some_function")
        
        # locals() access
        all_locals = locals()
        var = all_locals.get("some_var")
    
    def delete_attribute(self, obj, attr_name: str):
        """Using delattr"""
        # delattr with string literal
        delattr(obj, "temp_field")
        
        # delattr with variable
        delattr(obj, attr_name)


async def async_dynamic_call(obj, method_name: str):
    """Async function with dynamic calls"""
    method = getattr(obj, method_name)
    result = await method()
    return result
