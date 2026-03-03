/**
 * TypeScript/JavaScript dynamic patterns
 */

export class DynamicPatternExample {
    
    /**
     * Dynamic import patterns
     */
    async loadModuleDynamically(moduleName: string) {
        // Dynamic import with string literal
        const module1 = await import('./TaskCard');
        
        // Dynamic import with variable
        const module2 = await import(moduleName);
        
        // Dynamic import with template literal
        const module3 = await import(`./components/${moduleName}`);
        
        return module2;
    }
    
    /**
     * Computed member access patterns
     */
    callMethodByName(obj: any, methodName: string) {
        // Computed member access with string literal
        obj['processTask']();
        
        // Computed member access with variable
        obj[methodName]();
        
        // Nested computed access
        obj['nested']['method']();
    }
    
    /**
     * Dynamic property access
     */
    getPropertyDynamically(obj: any, propName: string) {
        // Property access with string literal
        const value1 = obj['status'];
        
        // Property access with variable
        const value2 = obj[propName];
        
        return value2;
    }
    
    /**
     * Reflection-like patterns
     */
    reflectOnObject(obj: any) {
        // Get all property names
        const keys = Object.keys(obj);
        
        // Call methods dynamically
        keys.forEach(key => {
            if (typeof obj[key] === 'function') {
                obj[key]();
            }
        });
    }
}

/**
 * Async dynamic patterns
 */
export async function asyncDynamicCall(obj: any, methodName: string) {
    // Async computed member call
    const result = await obj[methodName]();
    return result;
}

/**
 * Factory pattern with dynamic loading
 */
export async function createComponent(componentName: string) {
    // Dynamic import based on name
    const module = await import(`./components/${componentName}.tsx`);
    return module.default;
}
