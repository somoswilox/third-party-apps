/** @odoo-module **/
import {Component} from "@odoo/owl";
import {registry} from "@web/core/registry";
import {standardFieldProps} from "@web/views/fields/standard_field_props";

class CharColorPicker extends Component {
    static template = "bryntum_gantt_enterprise.CharColorPickerTemplate";
    static props = {...standardFieldProps};

    onColorChange(ev) {
        const newValue = ev.currentTarget.value;

        if (this.props.record && this.props.name) {
            this.props.record.update({[this.props.name]: newValue});
        } else {
            console.warn("Cannot update color — missing record or name");
        }
    }

    get value() {
        return this.props.record.data.color;
    }
}

registry.category("fields").add("char_color_picker", {
    component: CharColorPicker,
    supportedTypes: ["char"],
});
