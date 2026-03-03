import { defineComponent, PropType } from 'vue';
import { Task } from '../types/Task';
import { TaskCard } from './TaskCard';

export const TaskList = defineComponent({
  name: 'TaskList',

  props: {
    tasks: {
      type: Array as PropType<Task[]>,
      required: true
    },
    onTaskUpdate: {
      type: Function as PropType<(task: Task) => void>,
      required: false
    },
    onTaskDelete: {
      type: Function as PropType<(id: string) => void>,
      required: false
    }
  },

  setup(props) {
    const handleUpdate = (task: Task) => {
      if (props.onTaskUpdate) {
        props.onTaskUpdate(task);
      }
    };

    const handleDelete = (id: string) => {
      if (props.onTaskDelete) {
        props.onTaskDelete(id);
      }
    };

    return {
      handleUpdate,
      handleDelete
    };
  },

  render() {
    const { tasks } = this;

    if (tasks.length === 0) {
      return (
        <div class="text-center py-8 text-gray-500">
          No tasks found
        </div>
      );
    }

    return (
      <div class="task-list space-y-4">
        {tasks.map(task => (
          <TaskCard
            key={task.id}
            task={task}
            onUpdate={this.handleUpdate}
            onDelete={this.handleDelete}
          />
        ))}
      </div>
    );
  }
});
